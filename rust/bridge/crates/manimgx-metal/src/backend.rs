use std::collections::HashMap;
use std::ffi::c_void;
use std::sync::Arc;

use manimgx_core::color::srgb_to_linear;
use manimgx_core::scene::{ObjectId, RenderHint, Scene, TextureData};
use manimgx_core::uniform::CameraUniform;
use manimgx_core::vertex::Vertex;
use metal::foreign_types::{ForeignType, ForeignTypeRef};
use metal::*;
use objc::runtime::Object;
#[allow(unused_imports)]
use objc::{sel, sel_impl};

// ── Cached GPU resources ──

struct CachedMetalBuffers {
    vertex_buffer: Buffer,
    index_buffer: Buffer,
    index_count: u32,
}

struct CachedMetalTexture {
    texture: Texture,
}

// ── Per-frame slot for N-buffering ──
//
// Two backing modes:
//   Buffer: MTLBuffer (shared) backs output_texture. After GPU completes,
//           buffer.contents() is a direct pointer to BGRA pixels → pipe to ffmpeg.
//   IOSurface: IOSurface (shared) backs output_texture. Same memory is wrapped
//              by a CVPixelBuffer → fed directly to VideoToolbox. Zero readback.

enum SlotBacking {
    /// CPU-readable MTLBuffer backing store for ffmpeg encoding path.
    Buffer(Buffer),
    /// IOSurface + CVPixelBuffer for VideoToolbox encoding path.
    IOSurface {
        surface: crate::metal_encoder::IOSurfaceRef,
        cv_pixel_buffer: crate::metal_encoder::CVPixelBufferRef,
    },
}

impl Drop for SlotBacking {
    fn drop(&mut self) {
        if let SlotBacking::IOSurface { surface, cv_pixel_buffer } = self {
            unsafe {
                crate::metal_encoder::CVPixelBufferRelease(*cv_pixel_buffer);
                crate::metal_encoder::CFRelease(*surface as crate::metal_encoder::CFTypeRef);
            }
        }
        // Buffer variant: metal crate's Drop handles it
    }
}

struct FrameSlot {
    backing: SlotBacking,
    output_texture: Texture,           // buffer-backed or IOSurface-backed texture (resolve/render target)
    msaa_texture: Option<Texture>,     // private mode, sample_count>1
    depth_texture: Texture,            // private mode
    camera_buffer: Buffer,             // shared mode, per-slot
    object_buffer: Buffer,             // shared mode, per-slot
    pending_cmd_buffer: Option<*mut c_void>, // retained raw MTLCommandBuffer pointer
    /// Signaled by encoding thread after it finishes reading pixels from
    /// pixel_buffer.contents(). Main thread waits on this before reusing the slot.
    pub encoding_done: Arc<EncodingSignal>,
}

unsafe impl Send for FrameSlot {}

/// Condition-variable-based signal for encoding thread → main thread synchronization.
/// Replaces AtomicBool spin loop to avoid burning a CPU core.
pub struct EncodingSignal {
    done: std::sync::Mutex<bool>,
    cvar: std::sync::Condvar,
}

impl EncodingSignal {
    pub fn new(initial: bool) -> Self {
        Self {
            done: std::sync::Mutex::new(initial),
            cvar: std::sync::Condvar::new(),
        }
    }

    /// Mark as done and wake the waiting thread.
    pub fn signal_done(&self) {
        let mut done = self.done.lock().unwrap();
        *done = true;
        self.cvar.notify_one();
    }

    /// Wait until done, then return.
    pub fn wait_done(&self) {
        let mut done = self.done.lock().unwrap();
        while !*done {
            done = self.cvar.wait(done).unwrap();
        }
    }

    /// Reset to not-done (called before handing slot to encoding thread).
    pub fn reset(&self) {
        let mut done = self.done.lock().unwrap();
        *done = false;
    }
}


// ── Shader compilation ──

/// Replace `#include "types.h"` with actual types content for runtime MSL compilation.
fn prepare_shader(types_src: &str, shader_src: &str) -> String {
    shader_src.replace("#include \"types.h\"", types_src)
}

// ── MetalBackend ──

pub struct MetalBackend {
    device: Device,
    queue: CommandQueue,

    default_pipeline: RenderPipelineState,
    flat_no_cull_pipeline: RenderPipelineState,
    textured_pipeline: RenderPipelineState,

    depth_stencil_state: DepthStencilState,
    sampler_state: SamplerState,

    frame_slots: Vec<FrameSlot>,

    buffer_cache: HashMap<ObjectId, CachedMetalBuffers>,
    texture_cache: HashMap<ObjectId, CachedMetalTexture>,

    width: u32,
    height: u32,
    pixel_size: usize,

    // NV12 compute conversion (optional, only when pix_fmt="nv12")
    nv12_pipeline: Option<ComputePipelineState>,
    nv12_buffers: Vec<Buffer>,     // one per frame slot, W*H*3/2 bytes
    nv12_dims_buffer: Option<Buffer>, // constant [u32; 2] = [width, height]
    nv12_size: usize,
}

impl MetalBackend {
    /// Query the default Metal device for supported MSAA sample counts.
    /// Returns an error string if `sample_count` is not supported.
    pub fn validate_sample_count(sample_count: u32) -> Result<(), String> {
        let device = Device::system_default().ok_or("No Metal device found")?;
        if !device.supports_texture_sample_count(sample_count as u64) {
            let supported: Vec<u32> = [1, 2, 4, 8, 16]
                .iter()
                .copied()
                .filter(|&c| device.supports_texture_sample_count(c as u64))
                .collect();
            return Err(format!(
                "Metal device '{}' does not support msaa={}. Supported values: {:?}.",
                device.name(), sample_count, supported
            ));
        }
        Ok(())
    }

    pub fn new(width: u32, height: u32, sample_count: u32, n_buffers: u32, pix_fmt: &str) -> Self {
        let device = Device::system_default().expect("No Metal device found");
        let queue = device.new_command_queue();

        let use_nv12 = pix_fmt == "nv12";
        log::info!("Metal native backend: {} ({}x{}, MSAA={}, pix_fmt={})", device.name(), width, height, sample_count, pix_fmt);

        let pixel_format = MTLPixelFormat::BGRA8Unorm_sRGB;
        let bytes_per_row = (width * 4) as u64;
        let pixel_size = (width * height * 4) as usize;

        // Compile MSL shaders
        let types_src = include_str!("../../../shaders/metal/types.h");
        let opts = CompileOptions::new();

        let default_lib = device
            .new_library_with_source(&prepare_shader(types_src, include_str!("../../../shaders/metal/default.metal")), &opts)
            .unwrap_or_else(|e| panic!("default.metal compilation failed:\n{}", e));
        let flat_color_lib = device
            .new_library_with_source(&prepare_shader(types_src, include_str!("../../../shaders/metal/flat_color.metal")), &opts)
            .unwrap_or_else(|e| panic!("flat_color.metal compilation failed:\n{}", e));
        let text_lib = device
            .new_library_with_source(&prepare_shader(types_src, include_str!("../../../shaders/metal/text.metal")), &opts)
            .unwrap_or_else(|e| panic!("text.metal compilation failed:\n{}", e));

        // Vertex descriptor (shared across all pipelines)
        let vertex_desc = Self::create_vertex_descriptor();

        // Create 5 pipelines
        let default_pipeline = Self::create_pipeline(
            &device, &default_lib, vertex_desc, pixel_format, sample_count,
        );
        let flat_no_cull_pipeline = Self::create_pipeline(
            &device, &flat_color_lib, vertex_desc, pixel_format, sample_count,
        );
        let textured_pipeline = Self::create_pipeline(
            &device, &text_lib, vertex_desc, pixel_format, sample_count,
        );

        // Depth stencil state
        let depth_desc = DepthStencilDescriptor::new();
        depth_desc.set_depth_compare_function(MTLCompareFunction::Less);
        depth_desc.set_depth_write_enabled(true);
        let depth_stencil_state = device.new_depth_stencil_state(&depth_desc);

        // Sampler for text textures
        let sampler_desc = SamplerDescriptor::new();
        sampler_desc.set_address_mode_s(MTLSamplerAddressMode::ClampToEdge);
        sampler_desc.set_address_mode_t(MTLSamplerAddressMode::ClampToEdge);
        sampler_desc.set_mag_filter(MTLSamplerMinMagFilter::Linear);
        sampler_desc.set_min_filter(MTLSamplerMinMagFilter::Linear);
        let sampler_state = device.new_sampler(&sampler_desc);

        // NV12 compute pipeline (optional)
        let nv12_size = (width * height * 3 / 2) as usize;
        let (nv12_pipeline, nv12_dims_buffer) = if use_nv12 {
            assert!(width.is_multiple_of(2) && height.is_multiple_of(2), "NV12 requires even width and height");
            let nv12_src = include_str!("../../../shaders/metal/bgra_to_nv12.metal");
            let nv12_lib = device
                .new_library_with_source(nv12_src, &opts)
                .unwrap_or_else(|e| panic!("bgra_to_nv12.metal compilation failed:\n{}", e));
            let nv12_fn = nv12_lib.get_function("bgra_to_nv12", None)
                .expect("bgra_to_nv12 function not found");
            let pipeline = device.new_compute_pipeline_state_with_function(&nv12_fn)
                .unwrap_or_else(|e| panic!("Failed to create NV12 compute pipeline: {}", e));

            let dims: [u32; 2] = [width, height];
            let dims_buf = device.new_buffer_with_data(
                dims.as_ptr() as *const c_void,
                std::mem::size_of::<[u32; 2]>() as u64,
                MTLResourceOptions::StorageModeShared,
            );

            (Some(pipeline), Some(dims_buf))
        } else {
            (None, None)
        };

        // Create N frame slots with buffer-backed textures
        let n = n_buffers.max(1) as usize;
        let max_objects: usize = 512;
        let uniform_buf_size = (max_objects * 256) as u64;

        let mut nv12_buffers = Vec::new();

        let frame_slots: Vec<FrameSlot> = (0..n)
            .map(|_| {
                // Zero-copy pixel readback: create MTLBuffer, then create MTLTexture
                // backed by that buffer. GPU writes into the texture → pixels land in
                // the buffer's memory. After completion, buffer.contents() is a direct
                // pointer to the pixel data.
                let pixel_buffer = device.new_buffer(
                    pixel_size as u64,
                    MTLResourceOptions::StorageModeShared,
                );

                let tex_desc = TextureDescriptor::new();
                tex_desc.set_pixel_format(pixel_format);
                tex_desc.set_width(width as u64);
                tex_desc.set_height(height as u64);
                tex_desc.set_texture_type(MTLTextureType::D2);
                tex_desc.set_storage_mode(MTLStorageMode::Shared);
                tex_desc.set_usage(MTLTextureUsage::RenderTarget);

                let output_texture = pixel_buffer.new_texture_with_descriptor(
                    &tex_desc,
                    0,            // offset
                    bytes_per_row, // bytesPerRow
                );

                // NV12 output buffer per slot
                if use_nv12 {
                    nv12_buffers.push(device.new_buffer(
                        nv12_size as u64,
                        MTLResourceOptions::StorageModeShared,
                    ));
                }

                let msaa_texture = if sample_count > 1 {
                    Some(Self::create_msaa_texture(&device, width, height, pixel_format, sample_count))
                } else {
                    None
                };

                let depth_texture = Self::create_depth_texture(&device, width, height, sample_count);

                let camera_buffer = device.new_buffer(
                    std::mem::size_of::<CameraUniform>() as u64,
                    MTLResourceOptions::StorageModeShared,
                );

                let object_buffer = device.new_buffer(
                    uniform_buf_size,
                    MTLResourceOptions::StorageModeShared,
                );

                FrameSlot {
                    backing: SlotBacking::Buffer(pixel_buffer),
                    output_texture,
                    msaa_texture,
                    depth_texture,
                    camera_buffer,
                    object_buffer,
                    pending_cmd_buffer: None,
                    encoding_done: Arc::new(EncodingSignal::new(true)), // initially "done" (no work pending)
                }
            })
            .collect();

        Self {
            device,
            queue,
            default_pipeline,
            flat_no_cull_pipeline,
            textured_pipeline,
            depth_stencil_state,
            sampler_state,
            frame_slots,
            buffer_cache: HashMap::new(),
            texture_cache: HashMap::new(),
            width,
            height,
            pixel_size,
            nv12_pipeline,
            nv12_buffers,
            nv12_dims_buffer,
            nv12_size,
        }
    }

    pub fn pixel_size(&self) -> usize {
        self.pixel_size
    }

    /// Create a MetalBackend with IOSurface-backed frame slots for VideoToolbox encoding.
    /// Each slot gets its own IOSurface + CVPixelBuffer. No pixel readback needed.
    pub fn new_metal_encoder(width: u32, height: u32, sample_count: u32, n_buffers: u32) -> Self {
        let device = Device::system_default().expect("No Metal device found");
        let queue = device.new_command_queue();

        log::info!("Metal native backend (VT encoder): {} ({}x{}, MSAA={})", device.name(), width, height, sample_count);

        let pixel_format = MTLPixelFormat::BGRA8Unorm_sRGB;

        // Compile MSL shaders
        let types_src = include_str!("../../../shaders/metal/types.h");
        let opts = CompileOptions::new();

        let default_lib = device
            .new_library_with_source(&prepare_shader(types_src, include_str!("../../../shaders/metal/default.metal")), &opts)
            .unwrap_or_else(|e| panic!("default.metal compilation failed:\n{}", e));
        let flat_color_lib = device
            .new_library_with_source(&prepare_shader(types_src, include_str!("../../../shaders/metal/flat_color.metal")), &opts)
            .unwrap_or_else(|e| panic!("flat_color.metal compilation failed:\n{}", e));
        let text_lib = device
            .new_library_with_source(&prepare_shader(types_src, include_str!("../../../shaders/metal/text.metal")), &opts)
            .unwrap_or_else(|e| panic!("text.metal compilation failed:\n{}", e));

        let vertex_desc = Self::create_vertex_descriptor();

        let default_pipeline = Self::create_pipeline(&device, &default_lib, vertex_desc, pixel_format, sample_count);
        let flat_no_cull_pipeline = Self::create_pipeline(&device, &flat_color_lib, vertex_desc, pixel_format, sample_count);
        let textured_pipeline = Self::create_pipeline(&device, &text_lib, vertex_desc, pixel_format, sample_count);

        let depth_desc = DepthStencilDescriptor::new();
        depth_desc.set_depth_compare_function(MTLCompareFunction::Less);
        depth_desc.set_depth_write_enabled(true);
        let depth_stencil_state = device.new_depth_stencil_state(&depth_desc);

        let sampler_desc = SamplerDescriptor::new();
        sampler_desc.set_address_mode_s(MTLSamplerAddressMode::ClampToEdge);
        sampler_desc.set_address_mode_t(MTLSamplerAddressMode::ClampToEdge);
        sampler_desc.set_mag_filter(MTLSamplerMinMagFilter::Linear);
        sampler_desc.set_min_filter(MTLSamplerMinMagFilter::Linear);
        let sampler_state = device.new_sampler(&sampler_desc);

        let n = n_buffers.max(1) as usize;
        let max_objects: usize = 512;
        let uniform_buf_size = (max_objects * 256) as u64;

        let frame_slots: Vec<FrameSlot> = (0..n)
            .map(|_| {
                // Create IOSurface → IOSurface-backed MTLTexture → CVPixelBuffer
                let surface = crate::metal_encoder::create_iosurface(width, height);
                let cv_pixel_buffer = crate::metal_encoder::create_cv_pixel_buffer(surface, width, height);

                // Create MTLTextureDescriptor for IOSurface-backed texture
                let tex_desc = TextureDescriptor::new();
                tex_desc.set_pixel_format(pixel_format);
                tex_desc.set_width(width as u64);
                tex_desc.set_height(height as u64);
                tex_desc.set_texture_type(MTLTextureType::D2);
                tex_desc.set_storage_mode(MTLStorageMode::Shared);
                tex_desc.set_usage(MTLTextureUsage::RenderTarget);

                // Create Metal texture backed by IOSurface via objc runtime
                let output_texture = unsafe {
                    let raw_texture: *mut Object = objc::msg_send![
                        device.as_ptr() as *mut Object,
                        newTextureWithDescriptor: tex_desc.as_ptr() as *mut Object
                        iosurface: surface as *mut Object
                        plane: 0usize
                    ];
                    assert!(!raw_texture.is_null(), "Failed to create IOSurface-backed Metal texture");
                    Texture::from_ptr(raw_texture as *mut MTLTexture)
                };

                let msaa_texture = if sample_count > 1 {
                    Some(Self::create_msaa_texture(&device, width, height, pixel_format, sample_count))
                } else {
                    None
                };

                let depth_texture = Self::create_depth_texture(&device, width, height, sample_count);

                let camera_buffer = device.new_buffer(
                    std::mem::size_of::<CameraUniform>() as u64,
                    MTLResourceOptions::StorageModeShared,
                );

                let object_buffer = device.new_buffer(
                    uniform_buf_size,
                    MTLResourceOptions::StorageModeShared,
                );

                FrameSlot {
                    backing: SlotBacking::IOSurface { surface, cv_pixel_buffer },
                    output_texture,
                    msaa_texture,
                    depth_texture,
                    camera_buffer,
                    object_buffer,
                    pending_cmd_buffer: None,
                    encoding_done: Arc::new(EncodingSignal::new(true)),
                }
            })
            .collect();

        Self {
            device,
            queue,
            default_pipeline,
            flat_no_cull_pipeline,
            textured_pipeline,
            depth_stencil_state,
            sampler_state,
            frame_slots,
            buffer_cache: HashMap::new(),
            texture_cache: HashMap::new(),
            width,
            height,
            pixel_size: 0, // not used for IOSurface path
            nv12_pipeline: None,
            nv12_buffers: Vec::new(),
            nv12_dims_buffer: None,
            nv12_size: 0,
        }
    }

    // ── Texture creation helpers ──

    fn create_msaa_texture(device: &Device, width: u32, height: u32, format: MTLPixelFormat, sample_count: u32) -> Texture {
        let desc = TextureDescriptor::new();
        desc.set_pixel_format(format);
        desc.set_width(width as u64);
        desc.set_height(height as u64);
        desc.set_sample_count(sample_count as u64);
        desc.set_texture_type(MTLTextureType::D2Multisample);
        desc.set_storage_mode(MTLStorageMode::Private);
        desc.set_usage(MTLTextureUsage::RenderTarget);
        device.new_texture(&desc)
    }

    fn create_depth_texture(device: &Device, width: u32, height: u32, sample_count: u32) -> Texture {
        let desc = TextureDescriptor::new();
        desc.set_pixel_format(MTLPixelFormat::Depth32Float);
        desc.set_width(width as u64);
        desc.set_height(height as u64);
        desc.set_storage_mode(MTLStorageMode::Private);
        desc.set_usage(MTLTextureUsage::RenderTarget);
        if sample_count > 1 {
            desc.set_sample_count(sample_count as u64);
            desc.set_texture_type(MTLTextureType::D2Multisample);
        } else {
            desc.set_texture_type(MTLTextureType::D2);
        }
        device.new_texture(&desc)
    }

    // ── Pipeline creation ──

    fn create_vertex_descriptor() -> &'static VertexDescriptorRef {
        let desc = VertexDescriptor::new();

        // attribute(0): position — float3 at offset 0
        let attr0 = desc.attributes().object_at(0).unwrap();
        attr0.set_format(MTLVertexFormat::Float3);
        attr0.set_offset(0);
        attr0.set_buffer_index(0);

        // attribute(1): normal — float3 at offset 12
        let attr1 = desc.attributes().object_at(1).unwrap();
        attr1.set_format(MTLVertexFormat::Float3);
        attr1.set_offset(12);
        attr1.set_buffer_index(0);

        // attribute(2): color — float4 at offset 24
        let attr2 = desc.attributes().object_at(2).unwrap();
        attr2.set_format(MTLVertexFormat::Float4);
        attr2.set_offset(24);
        attr2.set_buffer_index(0);

        // layout(0): stride=40, per-vertex
        let layout0 = desc.layouts().object_at(0).unwrap();
        layout0.set_stride(40);
        layout0.set_step_function(MTLVertexStepFunction::PerVertex);

        desc
    }

    fn create_pipeline(
        device: &Device,
        library: &Library,
        vertex_desc: &VertexDescriptorRef,
        color_format: MTLPixelFormat,
        sample_count: u32,
    ) -> RenderPipelineState {
        let vertex_fn = library.get_function("vs_main", None)
            .expect("vs_main function not found in MSL library");
        let fragment_fn = library.get_function("fs_main", None)
            .expect("fs_main function not found in MSL library");

        let pipe_desc = RenderPipelineDescriptor::new();
        pipe_desc.set_vertex_function(Some(&vertex_fn));
        pipe_desc.set_fragment_function(Some(&fragment_fn));
        pipe_desc.set_vertex_descriptor(Some(vertex_desc));
        pipe_desc.set_sample_count(sample_count as u64);
        pipe_desc.set_depth_attachment_pixel_format(MTLPixelFormat::Depth32Float);

        // Color attachment with alpha blending (matches wgpu's ALPHA_BLENDING)
        let color_att = pipe_desc.color_attachments().object_at(0).unwrap();
        color_att.set_pixel_format(color_format);
        color_att.set_blending_enabled(true);
        color_att.set_source_rgb_blend_factor(MTLBlendFactor::SourceAlpha);
        color_att.set_destination_rgb_blend_factor(MTLBlendFactor::OneMinusSourceAlpha);
        color_att.set_source_alpha_blend_factor(MTLBlendFactor::SourceAlpha);
        color_att.set_destination_alpha_blend_factor(MTLBlendFactor::OneMinusSourceAlpha);
        color_att.set_rgb_blend_operation(MTLBlendOperation::Add);
        color_att.set_alpha_blend_operation(MTLBlendOperation::Add);

        device.new_render_pipeline_state(&pipe_desc)
            .unwrap_or_else(|e| panic!("Failed to create Metal render pipeline: {}", e))
    }

    // ── Buffer caching ──

    fn get_or_cache_buffers(&mut self, obj_id: ObjectId, vertices: &[Vertex], indices: &[u32]) -> &CachedMetalBuffers {
        self.buffer_cache.entry(obj_id).or_insert_with(|| {
            let vertex_data = bytemuck::cast_slice::<Vertex, u8>(vertices);
            let index_data = bytemuck::cast_slice::<u32, u8>(indices);

            let vertex_buffer = self.device.new_buffer_with_data(
                vertex_data.as_ptr() as *const c_void,
                vertex_data.len() as u64,
                MTLResourceOptions::StorageModeShared,
            );
            let index_buffer = self.device.new_buffer_with_data(
                index_data.as_ptr() as *const c_void,
                index_data.len() as u64,
                MTLResourceOptions::StorageModeShared,
            );

            CachedMetalBuffers {
                vertex_buffer,
                index_buffer,
                index_count: indices.len() as u32,
            }
        })
    }

    fn get_or_cache_texture(&mut self, obj_id: ObjectId, texture_data: &TextureData) -> &CachedMetalTexture {
        self.texture_cache.entry(obj_id).or_insert_with(|| {
            let desc = TextureDescriptor::new();
            desc.set_pixel_format(MTLPixelFormat::RGBA8Unorm_sRGB);
            desc.set_width(texture_data.width as u64);
            desc.set_height(texture_data.height as u64);
            desc.set_storage_mode(MTLStorageMode::Shared);
            desc.set_usage(MTLTextureUsage::ShaderRead);
            desc.set_texture_type(MTLTextureType::D2);

            let texture = self.device.new_texture(&desc);

            let region = MTLRegion::new_2d(0, 0, texture_data.width as u64, texture_data.height as u64);
            texture.replace_region(
                region,
                0, // mipmap level
                texture_data.rgba.as_ptr() as *const c_void,
                (4 * texture_data.width) as u64, // bytes per row
            );

            CachedMetalTexture { texture }
        })
    }

    // ── Render a single frame into a slot ──

    /// Build clear color from scene background (sRGB → linear for sRGB framebuffer).
    pub fn clear_color(scene: &Scene) -> MTLClearColor {
        MTLClearColor {
            red: srgb_to_linear(scene.background[0]) as f64,
            green: srgb_to_linear(scene.background[1]) as f64,
            blue: srgb_to_linear(scene.background[2]) as f64,
            alpha: scene.background[3] as f64,
        }
    }

    /// Get the encoding_done signal for a slot (used by render_loop for synchronization).
    pub fn slot_encoding_done(&self, slot_idx: usize) -> &Arc<EncodingSignal> {
        &self.frame_slots[slot_idx].encoding_done
    }

    /// Wait until the encoding thread has finished reading from this slot's pixel buffer.
    /// Must be called before submitting new GPU work to this slot.
    pub fn wait_encoding_done(&self, slot_idx: usize) {
        self.frame_slots[slot_idx].encoding_done.wait_done();
    }

    /// Encode and submit a render pass for one frame. Does NOT wait for completion.
    /// NV12 compute writes to self.nv12_buffers[slot_idx] (per-slot buffer).
    pub fn submit_frame(
        &mut self,
        scene: &Scene,
        cam_bytes: &[u8],
        uniform_staging: &[u8],
        total_uniform_bytes: usize,
        draw_cmds: &[(usize, usize)],
        clear_color: MTLClearColor,
        slot_idx: usize,
    ) {
        self.submit_frame_impl(scene, cam_bytes, uniform_staging, total_uniform_bytes, draw_cmds, clear_color, slot_idx, None);
    }

    /// Like submit_frame, but NV12 compute writes to an external pool buffer instead.
    pub fn submit_frame_nv12(
        &mut self,
        scene: &Scene,
        cam_bytes: &[u8],
        uniform_staging: &[u8],
        total_uniform_bytes: usize,
        draw_cmds: &[(usize, usize)],
        clear_color: MTLClearColor,
        slot_idx: usize,
        nv12_target: &Buffer,
    ) {
        self.submit_frame_impl(scene, cam_bytes, uniform_staging, total_uniform_bytes, draw_cmds, clear_color, slot_idx, Some(nv12_target));
    }

    fn submit_frame_impl(
        &mut self,
        scene: &Scene,
        cam_bytes: &[u8],
        uniform_staging: &[u8],
        total_uniform_bytes: usize,
        draw_cmds: &[(usize, usize)], // (obj_idx, uniform_slot)
        clear_color: MTLClearColor,
        slot_idx: usize,
        nv12_override: Option<&Buffer>,
    ) {
        let slot = &self.frame_slots[slot_idx];

        // Write camera uniform via direct memcpy
        unsafe {
            let dst = slot.camera_buffer.contents() as *mut u8;
            std::ptr::copy_nonoverlapping(cam_bytes.as_ptr(), dst, cam_bytes.len());
        }

        // Write object uniforms
        if total_uniform_bytes > 0 {
            unsafe {
                let dst = slot.object_buffer.contents() as *mut u8;
                std::ptr::copy_nonoverlapping(
                    uniform_staging.as_ptr(),
                    dst,
                    total_uniform_bytes,
                );
            }
        }

        // Pre-cache textures (must happen before encoding)
        for &(obj_idx, _) in draw_cmds {
            let obj = &scene.objects[obj_idx];
            if let RenderHint::Textured = &obj.render_hint {
                if let Some(ref tex_data) = obj.texture_data {
                    self.get_or_cache_texture(obj.id, tex_data);
                }
            }
        }

        // Pre-cache geometry
        for &(obj_idx, _) in draw_cmds {
            let obj = &scene.objects[obj_idx];
            self.get_or_cache_buffers(obj.id, &obj.vertices, &obj.indices);
        }

        let cmd_buf = self.queue.new_command_buffer();

        // Configure render pass descriptor
        let pass_desc = RenderPassDescriptor::new();

        // Color attachment
        let color_att = pass_desc.color_attachments().object_at(0).unwrap();
        if let Some(ref msaa_tex) = self.frame_slots[slot_idx].msaa_texture {
            color_att.set_texture(Some(msaa_tex));
            color_att.set_resolve_texture(Some(&self.frame_slots[slot_idx].output_texture));
            color_att.set_store_action(MTLStoreAction::MultisampleResolve);
        } else {
            color_att.set_texture(Some(&self.frame_slots[slot_idx].output_texture));
            color_att.set_store_action(MTLStoreAction::Store);
        }
        color_att.set_load_action(MTLLoadAction::Clear);
        color_att.set_clear_color(clear_color);

        // Depth attachment
        let depth_att = pass_desc.depth_attachment().unwrap();
        depth_att.set_texture(Some(&self.frame_slots[slot_idx].depth_texture));
        depth_att.set_load_action(MTLLoadAction::Clear);
        depth_att.set_clear_depth(1.0);
        depth_att.set_store_action(MTLStoreAction::DontCare);

        let encoder = cmd_buf.new_render_command_encoder(pass_desc);

        // Set viewport
        encoder.set_viewport(MTLViewport {
            originX: 0.0,
            originY: 0.0,
            width: self.width as f64,
            height: self.height as f64,
            znear: 0.0,
            zfar: 1.0,
        });

        // Set depth stencil state
        encoder.set_depth_stencil_state(&self.depth_stencil_state);

        // Set front face winding (CCW, matching wgpu)
        encoder.set_front_facing_winding(MTLWinding::CounterClockwise);

        // Draw each object
        let slot = &self.frame_slots[slot_idx];
        let uniform_alignment: usize = 256;

        for &(obj_idx, uniform_slot) in draw_cmds {
            let obj = &scene.objects[obj_idx];
            let is_textured = matches!(&obj.render_hint, RenderHint::Textured);

            // Select pipeline and cull mode based on render hint
            let (pipeline, cull_mode) = match &obj.render_hint {
                RenderHint::Default => (&self.default_pipeline, MTLCullMode::None),
                RenderHint::FlatUnlit => (&self.flat_no_cull_pipeline, MTLCullMode::None),
                RenderHint::Textured => (&self.textured_pipeline, MTLCullMode::None),
            };

            encoder.set_render_pipeline_state(pipeline);
            encoder.set_cull_mode(cull_mode);

            let cached = self.buffer_cache.get(&obj.id).unwrap();
            let obj_offset = (uniform_slot * uniform_alignment) as u64;

            // Buffer index 0: vertex data
            encoder.set_vertex_buffer(0, Some(&cached.vertex_buffer), 0);
            // Buffer index 1: camera uniform (vertex shader only)
            encoder.set_vertex_buffer(1, Some(&slot.camera_buffer), 0);
            // Buffer index 2: object uniform (vertex AND fragment)
            encoder.set_vertex_buffer(2, Some(&slot.object_buffer), obj_offset);
            encoder.set_fragment_buffer(2, Some(&slot.object_buffer), obj_offset);

            // Texture binding for text objects
            if is_textured {
                if let Some(tex_cached) = self.texture_cache.get(&obj.id) {
                    encoder.set_fragment_texture(0, Some(&tex_cached.texture));
                    encoder.set_fragment_sampler_state(0, Some(&self.sampler_state));
                }
            }

            // Draw indexed primitives
            encoder.draw_indexed_primitives(
                MTLPrimitiveType::Triangle,
                cached.index_count as u64,
                MTLIndexType::UInt32,
                &cached.index_buffer,
                0,
            );
        }

        encoder.end_encoding();

        // NV12 compute pass: convert BGRA → NV12 on the same command buffer
        if let Some(ref nv12_pipeline) = self.nv12_pipeline {
            let pixel_buf = match &self.frame_slots[slot_idx].backing {
                SlotBacking::Buffer(buf) => buf,
                _ => panic!("NV12 compute requires Buffer-backed slot"),
            };
            let nv12_buf = nv12_override.unwrap_or(&self.nv12_buffers[slot_idx]);
            let dims_buf = self.nv12_dims_buffer.as_ref().unwrap();

            let compute_enc = cmd_buf.new_compute_command_encoder();
            compute_enc.set_compute_pipeline_state(nv12_pipeline);
            compute_enc.set_buffer(0, Some(pixel_buf), 0);
            compute_enc.set_buffer(1, Some(nv12_buf), 0);
            compute_enc.set_buffer(2, Some(dims_buf), 0);

            // Each thread processes a 4×2 pixel block, threadgroup is 8×8 threads (32×16 pixels)
            let threadgroup_size = MTLSize::new(8, 8, 1);
            let grid_w = (self.width as u64).div_ceil(4);   // ceil(width / 4)
            let grid_h = (self.height as u64).div_ceil(2);  // ceil(height / 2)
            compute_enc.dispatch_thread_groups(
                MTLSize::new(
                    grid_w.div_ceil(8),   // ceil(grid_w / threadgroup_w)
                    grid_h.div_ceil(8),   // ceil(grid_h / threadgroup_h)
                    1,
                ),
                threadgroup_size,
            );
            compute_enc.end_encoding();
        }

        cmd_buf.commit();

        // Retain the command buffer so we can wait on it later
        let raw_ptr = cmd_buf.as_ptr() as *mut c_void;
        unsafe {
            let _: *mut Object = objc::msg_send![raw_ptr as *mut Object, retain];
        }
        self.frame_slots[slot_idx].pending_cmd_buffer = Some(raw_ptr);
    }

    /// Wait for a slot's command buffer to complete, then return a direct pointer
    /// to the pixel data in the buffer-backed texture's MTLBuffer.
    ///
    /// ZERO COPY: The returned pointer points directly into the MTLBuffer's shared
    /// memory. The GPU wrote pixels there during the render pass resolve. No getBytes,
    /// no staging buffer, no memcpy. The pointer is valid until the next GPU submission
    /// to this slot.
    ///
    /// The caller MUST call `mark_encoding_start` before passing this pointer to
    /// the encoding thread, and the encoding thread MUST set `encoding_done` when
    /// finished reading. The main thread will spin on `wait_encoding_done` before
    /// reusing this slot.
    pub fn drain_slot(&mut self, slot_idx: usize) -> *const u8 {
        let slot = &mut self.frame_slots[slot_idx];

        if let Some(raw_ptr) = slot.pending_cmd_buffer.take() {
            unsafe {
                // Wait for GPU completion
                let _: () = objc::msg_send![raw_ptr as *mut Object, waitUntilCompleted];
                // Release the retained command buffer
                let _: () = objc::msg_send![raw_ptr as *mut Object, release];
            }
        }

        // Return direct pointer to pixel data in the buffer-backed texture's backing store
        match &slot.backing {
            SlotBacking::Buffer(buf) => buf.contents() as *const u8,
            SlotBacking::IOSurface { .. } => panic!("drain_slot called on IOSurface-backed slot; use drain_slot_metal"),
        }
    }

    /// Wait for GPU completion on an IOSurface-backed slot. No pixel readback —
    /// the IOSurface already has the data for VideoToolbox to read.
    pub fn drain_slot_metal(&mut self, slot_idx: usize) {
        let slot = &mut self.frame_slots[slot_idx];

        if let Some(raw_ptr) = slot.pending_cmd_buffer.take() {
            unsafe {
                let _: () = objc::msg_send![raw_ptr as *mut Object, waitUntilCompleted];
                let _: () = objc::msg_send![raw_ptr as *mut Object, release];
            }
        }
    }

    /// Wait for GPU completion on an IOSurface-backed slot and return GPU timing.
    /// Used by the profiling render loop.
    pub fn drain_slot_metal_timed(&mut self, slot_idx: usize) -> f64 {
        let slot = &mut self.frame_slots[slot_idx];
        let mut gpu_duration = 0.0;

        if let Some(raw_ptr) = slot.pending_cmd_buffer.take() {
            unsafe {
                let _: () = objc::msg_send![raw_ptr as *mut Object, waitUntilCompleted];

                let gpu_start: f64 = objc::msg_send![raw_ptr as *mut Object, GPUStartTime];
                let gpu_end: f64 = objc::msg_send![raw_ptr as *mut Object, GPUEndTime];
                if gpu_end > gpu_start {
                    gpu_duration = gpu_end - gpu_start;
                }

                let _: () = objc::msg_send![raw_ptr as *mut Object, release];
            }
        }

        gpu_duration
    }

    /// Get the CVPixelBuffer for a slot (IOSurface-backed slots only).
    pub fn slot_cv_pixel_buffer(&self, slot_idx: usize) -> crate::metal_encoder::CVPixelBufferRef {
        match &self.frame_slots[slot_idx].backing {
            SlotBacking::IOSurface { cv_pixel_buffer, .. } => *cv_pixel_buffer,
            SlotBacking::Buffer(_) => panic!("slot_cv_pixel_buffer called on Buffer-backed slot"),
        }
    }

    /// Mark that the encoding thread is about to start reading from this slot's pixel buffer.
    pub fn mark_encoding_start(&self, slot_idx: usize) {
        self.frame_slots[slot_idx].encoding_done.reset();
    }

    /// Wait for a slot's command buffer to complete, then return a direct pointer
    /// to the pixel data AND the GPU execution time in seconds.
    ///
    /// Same as `drain_slot` but reads `MTLCommandBuffer.GPUStartTime/GPUEndTime`
    /// before releasing the command buffer. Used by the profiling render loop.
    pub fn drain_slot_timed(&mut self, slot_idx: usize) -> (*const u8, f64) {
        let slot = &mut self.frame_slots[slot_idx];
        let mut gpu_duration = 0.0;

        if let Some(raw_ptr) = slot.pending_cmd_buffer.take() {
            unsafe {
                let _: () = objc::msg_send![raw_ptr as *mut Object, waitUntilCompleted];

                // Read GPU timing from completed command buffer
                let gpu_start: f64 = objc::msg_send![raw_ptr as *mut Object, GPUStartTime];
                let gpu_end: f64 = objc::msg_send![raw_ptr as *mut Object, GPUEndTime];
                if gpu_end > gpu_start {
                    gpu_duration = gpu_end - gpu_start;
                }

                let _: () = objc::msg_send![raw_ptr as *mut Object, release];
            }
        }

        match &slot.backing {
            SlotBacking::Buffer(buf) => (buf.contents() as *const u8, gpu_duration),
            SlotBacking::IOSurface { .. } => panic!("drain_slot_timed called on IOSurface-backed slot"),
        }
    }

    /// Wait for GPU completion, then return pointer to the NV12 buffer for this slot.
    pub fn drain_slot_nv12(&mut self, slot_idx: usize) -> *const u8 {
        let slot = &mut self.frame_slots[slot_idx];

        if let Some(raw_ptr) = slot.pending_cmd_buffer.take() {
            unsafe {
                let _: () = objc::msg_send![raw_ptr as *mut Object, waitUntilCompleted];
                let _: () = objc::msg_send![raw_ptr as *mut Object, release];
            }
        }

        self.nv12_buffers[slot_idx].contents() as *const u8
    }

    /// Wait for GPU completion, return NV12 buffer pointer + GPU timing.
    pub fn drain_slot_nv12_timed(&mut self, slot_idx: usize) -> (*const u8, f64) {
        let slot = &mut self.frame_slots[slot_idx];
        let mut gpu_duration = 0.0;

        if let Some(raw_ptr) = slot.pending_cmd_buffer.take() {
            unsafe {
                let _: () = objc::msg_send![raw_ptr as *mut Object, waitUntilCompleted];

                let gpu_start: f64 = objc::msg_send![raw_ptr as *mut Object, GPUStartTime];
                let gpu_end: f64 = objc::msg_send![raw_ptr as *mut Object, GPUEndTime];
                if gpu_end > gpu_start {
                    gpu_duration = gpu_end - gpu_start;
                }

                let _: () = objc::msg_send![raw_ptr as *mut Object, release];
            }
        }

        (self.nv12_buffers[slot_idx].contents() as *const u8, gpu_duration)
    }

    /// NV12 frame size in bytes (W*H*3/2). Zero if NV12 not enabled.
    pub fn nv12_size(&self) -> usize {
        self.nv12_size
    }

    /// Whether NV12 compute conversion is enabled.
    pub fn has_nv12(&self) -> bool {
        self.nv12_pipeline.is_some()
    }

    /// Create standalone NV12 MTLBuffers for the elastic pool (not tied to frame slots).
    pub fn create_nv12_buffers(&self, count: usize) -> Vec<Buffer> {
        (0..count).map(|_| {
            self.device.new_buffer(self.nv12_size as u64, MTLResourceOptions::StorageModeShared)
        }).collect()
    }

    /// Number of frame slots.
    pub fn n_slots(&self) -> usize {
        self.frame_slots.len()
    }
}
