use std::collections::HashMap;

use manimgx_core::color::srgb_to_linear;
use manimgx_core::scene::{ObjectId, RenderHint, Scene};
use manimgx_core::uniform::{CameraUniform, ObjectUniform};
use manimgx_core::vertex::Vertex;
use bytemuck;
use wgpu::util::DeviceExt;

use manimgx_core::encoder::FfmpegCodec;
use crate::gpu::GpuContext;
use crate::pipeline::RenderPipelines;


/// Which encoder backend to use for video output.
pub enum EncoderBackend {
    /// GPU → staging → CPU readback → ffmpeg pipe (h264_videotoolbox or h264_vaapi)
    Ffmpeg(FfmpegCodec),
    /// GPU → NV12 compute → staging → CPU readback → in-process x264 FFI (no subprocess)
    X264,
}

/// Cached GPU buffers for a scene object (geometry never changes).
struct CachedObjectBuffers {
    vertex_buffer: wgpu::Buffer,
    index_buffer: wgpu::Buffer,
    index_count: u32,
}

/// Cached GPU texture resources for a textured object (uploaded once).
struct CachedTextureBindGroup {
    _texture: wgpu::Texture,
    _view: wgpu::TextureView,
    _sampler: wgpu::Sampler,
    bind_group: wgpu::BindGroup,
}

/// Draw command for one object in one frame.
struct DrawCmd {
    obj_idx: usize,
    uniform_slot: usize,
}

/// Pre-allocated GPU resources for rendering.
struct FrameResources {
    /// MSAA render target (only when sample_count > 1). Kept alive for msaa_view / nv12 bind group.
    _msaa_texture: Option<wgpu::Texture>,
    msaa_view: Option<wgpu::TextureView>,
    /// Output texture (sample_count=1) — copied to staging for readback.
    /// When MSAA is on, this is the resolve target. When off, this is the render target.
    output_texture: wgpu::Texture,
    output_view: wgpu::TextureView,
    _depth_texture: wgpu::Texture,
    depth_view: wgpu::TextureView,
    staging_buffer: wgpu::Buffer,
    padded_bytes_per_row: u32,
    unpadded_bytes_per_row: u32,
    pixel_size: usize,
    width: u32,
    height: u32,
    camera_buffer: wgpu::Buffer,
    camera_bind_group: wgpu::BindGroup,
    object_uniform_buffer: wgpu::Buffer,
    object_bind_group: wgpu::BindGroup,
    uniform_alignment: usize,
    /// CPU staging for object uniforms: max_objects * alignment bytes
    uniform_staging: Vec<u8>,
    rows_contiguous: bool,
    // NV12 compute conversion resources
    /// Kept alive to back nv12_bind_group
    _nv12_view: Option<wgpu::TextureView>,
    nv12_storage_buffer: Option<wgpu::Buffer>,
    nv12_staging_buffer: Option<wgpu::Buffer>,
    nv12_bind_group: Option<wgpu::BindGroup>,
    nv12_size: usize,
}

impl FrameResources {
    #[allow(clippy::too_many_arguments)]
    fn new(
        device: &wgpu::Device,
        width: u32,
        height: u32,
        color_format: wgpu::TextureFormat,
        camera_bgl: &wgpu::BindGroupLayout,
        object_bgl: &wgpu::BindGroupLayout,
        num_objects: usize,
        sample_count: u32,
        use_nv12: bool,
        nv12_bgl: Option<&wgpu::BindGroupLayout>,
    ) -> Self {
        // Non-sRGB view format for NV12 compute shader (keeps gamma-encoded values)
        let non_srgb_format = match color_format {
            wgpu::TextureFormat::Rgba8UnormSrgb => wgpu::TextureFormat::Rgba8Unorm,
            wgpu::TextureFormat::Bgra8UnormSrgb => wgpu::TextureFormat::Bgra8Unorm,
            other => other,
        };

        // MSAA render target (only when sample_count > 1)
        // Hardware MSAA resolve is essentially free (dedicated fixed-function silicon on tile flush).
        // The NV12 compute shader always reads the resolved 1x output_texture, not the MSAA texture.
        let (msaa_texture, msaa_view) = if sample_count > 1 {
            let tex = device.create_texture(&wgpu::TextureDescriptor {
                label: Some("msaa_texture"),
                size: wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count,
                dimension: wgpu::TextureDimension::D2,
                format: color_format,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                view_formats: &[],
            });
            let view = tex.create_view(&wgpu::TextureViewDescriptor::default());
            (Some(tex), Some(view))
        } else {
            (None, None)
        };

        // Output texture (1x) — resolve target when MSAA, or direct render target.
        // NV12 compute shader reads from this after hardware MSAA resolve.
        let mut output_usage =
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC;
        let mut output_view_formats: Vec<wgpu::TextureFormat> = vec![];
        if use_nv12 {
            output_usage |= wgpu::TextureUsages::TEXTURE_BINDING;
            output_view_formats.push(non_srgb_format);
        }
        let output_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("output_texture"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: color_format,
            usage: output_usage,
            view_formats: &output_view_formats,
        });
        let output_view = output_texture.create_view(&wgpu::TextureViewDescriptor::default());

        // Depth buffer (must match sample_count)
        let depth_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("depth_texture"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth32Float,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        });
        let depth_view = depth_texture.create_view(&wgpu::TextureViewDescriptor::default());

        let bytes_per_pixel = 4u32;
        let unpadded_bytes_per_row = width * bytes_per_pixel;
        let align = wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
        let padded_bytes_per_row = unpadded_bytes_per_row.div_ceil(align) * align;
        let rows_contiguous = padded_bytes_per_row == unpadded_bytes_per_row;
        let pixel_size = (width * height * bytes_per_pixel) as usize;
        let staging_size = (padded_bytes_per_row * height) as u64;

        let staging_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("staging"),
            size: staging_size,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });

        let cam_size = std::mem::size_of::<CameraUniform>() as u64;
        let camera_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("camera"),
            size: cam_size,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let camera_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("camera_bg"),
            layout: camera_bgl,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: camera_buffer.as_entire_binding(),
            }],
        });

        let uniform_alignment = device.limits().min_uniform_buffer_offset_alignment as usize;
        let max_objects = num_objects.max(1);
        let buffer_size = (max_objects * uniform_alignment) as u64;

        let object_uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("object_uniform_buffer"),
            size: buffer_size,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let uniform_size = std::mem::size_of::<ObjectUniform>() as u64;
        let object_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("object_bind_group"),
            layout: object_bgl,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                    buffer: &object_uniform_buffer,
                    offset: 0,
                    size: Some(std::num::NonZero::new(uniform_size).unwrap()),
                }),
            }],
        });

        let uniform_staging = vec![0u8; max_objects * uniform_alignment];

        // NV12 compute conversion resources
        let nv12_size = (width * height * 3 / 2) as usize;
        let (nv12_view, nv12_storage_buffer, nv12_staging_buffer, nv12_bind_group) = if use_nv12 {
            let bgl = nv12_bgl.expect("NV12 bind group layout required when use_nv12=true");

            // Non-sRGB view of the resolved 1x output_texture.
            // Hardware MSAA resolve writes here; compute shader reads raw gamma-encoded bytes.
            let nv12_view = output_texture.create_view(&wgpu::TextureViewDescriptor {
                format: Some(non_srgb_format),
                ..Default::default()
            });

            let storage_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("nv12_storage"),
                size: nv12_size as u64,
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            });

            let staging_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("nv12_staging"),
                size: nv12_size as u64,
                usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });

            let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("nv12_bg"),
                layout: bgl,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::TextureView(&nv12_view),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: storage_buf.as_entire_binding(),
                    },
                ],
            });

            (
                Some(nv12_view),
                Some(storage_buf),
                Some(staging_buf),
                Some(bind_group),
            )
        } else {
            (None, None, None, None)
        };

        Self {
            _msaa_texture: msaa_texture,
            msaa_view,
            output_texture,
            output_view,
            _depth_texture: depth_texture,
            depth_view,
            staging_buffer,
            padded_bytes_per_row,
            unpadded_bytes_per_row,
            pixel_size,
            width,
            height,
            camera_buffer,
            camera_bind_group,
            object_uniform_buffer,
            object_bind_group,
            uniform_alignment,
            uniform_staging,
            rows_contiguous,
            _nv12_view: nv12_view,
            nv12_storage_buffer,
            nv12_staging_buffer,
            nv12_bind_group,
            nv12_size,
        }
    }

    /// Read pixels from the mapped staging buffer into a pre-allocated buffer.
    fn read_pixels_into(&self, dst: &mut Vec<u8>) {
        let data = self.staging_buffer.slice(..).get_mapped_range();

        if self.rows_contiguous {
            dst.clear();
            dst.extend_from_slice(&data[..self.pixel_size]);
        } else {
            dst.clear();
            dst.reserve(self.pixel_size);
            for row in 0..self.height {
                let start = (row * self.padded_bytes_per_row) as usize;
                let end = start + self.unpadded_bytes_per_row as usize;
                dst.extend_from_slice(&data[start..end]);
            }
        }

        drop(data);
        self.staging_buffer.unmap();
    }

    /// Read NV12 data from the mapped NV12 staging buffer (no row padding).
    fn read_nv12_into(&self, dst: &mut Vec<u8>) {
        let buf = self.nv12_staging_buffer.as_ref().unwrap();
        let data = buf.slice(..).get_mapped_range();
        dst.clear();
        dst.extend_from_slice(&data[..self.nv12_size]);
        drop(data);
        buf.unmap();
    }

    /// Read NV12 data from the mapped NV12 staging buffer into a pre-existing slice.
    fn read_nv12_into_slice(&self, dst: &mut [u8]) {
        let buf = self.nv12_staging_buffer.as_ref().unwrap();
        let data = buf.slice(..).get_mapped_range();
        dst[..self.nv12_size].copy_from_slice(&data[..self.nv12_size]);
        drop(data);
        buf.unmap();
    }
}

pub struct Renderer {
    pub gpu: GpuContext,
    pub pipelines: RenderPipelines,
    pub color_format: wgpu::TextureFormat,
    pub sample_count: u32,
    nv12_pipeline: wgpu::ComputePipeline,
    nv12_bind_group_layout: wgpu::BindGroupLayout,
}

/// Trait abstracting different frame encoding backends for the unified render loop.
pub trait FrameWriter {
    /// Write a rendered frame's pixel data to the encoder.
    fn write_frame(&mut self, pixels: &[u8]);
    /// Handle a duplicate frame (same scene state as previous).
    fn write_duplicate(&mut self);
    /// Finalize the writer (flush, join threads, etc).
    fn finish(&mut self);
}

/// Frame writer for ffmpeg-based encoding with a background writer thread and buffer pool.
pub struct FfmpegWriter {
    tx: Option<std::sync::mpsc::SyncSender<Option<Vec<u8>>>>,
    pool_rx: std::sync::mpsc::Receiver<Vec<u8>>,
    writer_handle: Option<std::thread::JoinHandle<()>>,
}

impl FfmpegWriter {
    pub fn new(encoder: manimgx_core::encoder::FfmpegEncoder, pixel_size: usize) -> Self {
        let pool_size = 4;
        let (tx, rx) = std::sync::mpsc::sync_channel::<Option<Vec<u8>>>(2);
        let (pool_tx, pool_rx) = std::sync::mpsc::sync_channel::<Vec<u8>>(pool_size);

        for _ in 0..pool_size {
            pool_tx.send(vec![0u8; pixel_size]).unwrap();
        }

        let handle = std::thread::spawn(move || {
            let mut encoder = encoder;
            let mut last_written = vec![0u8; pixel_size];
            while let Ok(data) = rx.recv() {
                match data {
                    Some(pixels) => {
                        encoder.write_frame(&pixels);
                        last_written.copy_from_slice(&pixels);
                        let _ = pool_tx.send(pixels);
                    }
                    None => {
                        encoder.write_frame(&last_written);
                    }
                }
            }
            encoder.finish();
        });

        Self {
            tx: Some(tx),
            pool_rx,
            writer_handle: Some(handle),
        }
    }
}

impl FrameWriter for FfmpegWriter {
    fn write_frame(&mut self, pixels: &[u8]) {
        let mut buf = self.pool_rx.recv().unwrap();
        buf[..pixels.len()].copy_from_slice(pixels);
        self.tx.as_ref().unwrap().send(Some(buf)).unwrap();
    }

    fn write_duplicate(&mut self) {
        self.tx.as_ref().unwrap().send(None).unwrap();
    }

    fn finish(&mut self) {
        self.tx.take();
        if let Some(handle) = self.writer_handle.take() {
            handle.join().unwrap();
        }
    }
}

impl Renderer {
    pub fn new(sample_count: u32) -> Self {
        Self::new_with_format(sample_count, wgpu::TextureFormat::Rgba8UnormSrgb)
    }

    pub fn new_with_format(sample_count: u32, color_format: wgpu::TextureFormat) -> Self {
        let gpu = GpuContext::new();
        let pipelines = RenderPipelines::new(&gpu.device, color_format, sample_count);

        // NV12 compute pipeline — always reads the resolved 1x output_texture (non-MSAA).
        // Hardware MSAA resolve is free; manual resolve in compute shader is 10x slower.
        let nv12_shader_src = include_str!("../../../shaders/nv12_convert.wgsl");
        let nv12_shader = gpu
            .device
            .create_shader_module(wgpu::ShaderModuleDescriptor {
                label: Some("nv12_convert_shader"),
                source: wgpu::ShaderSource::Wgsl(nv12_shader_src.into()),
            });

        let nv12_bind_group_layout =
            gpu.device
                .create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                    label: Some("nv12_bgl"),
                    entries: &[
                        wgpu::BindGroupLayoutEntry {
                            binding: 0,
                            visibility: wgpu::ShaderStages::COMPUTE,
                            ty: wgpu::BindingType::Texture {
                                sample_type: wgpu::TextureSampleType::Float { filterable: false },
                                view_dimension: wgpu::TextureViewDimension::D2,
                                multisampled: false,
                            },
                            count: None,
                        },
                        wgpu::BindGroupLayoutEntry {
                            binding: 1,
                            visibility: wgpu::ShaderStages::COMPUTE,
                            ty: wgpu::BindingType::Buffer {
                                ty: wgpu::BufferBindingType::Storage { read_only: false },
                                has_dynamic_offset: false,
                                min_binding_size: None,
                            },
                            count: None,
                        },
                    ],
                });

        let nv12_pipeline_layout =
            gpu.device
                .create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                    label: Some("nv12_pipeline_layout"),
                    bind_group_layouts: &[&nv12_bind_group_layout],
                    push_constant_ranges: &[],
                });

        let nv12_pipeline =
            gpu.device
                .create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                    label: Some("nv12_pipeline"),
                    layout: Some(&nv12_pipeline_layout),
                    module: &nv12_shader,
                    entry_point: Some("nv12_convert"),
                    compilation_options: Default::default(),
                    cache: None,
                });

        Self {
            gpu,
            pipelines,
            color_format,
            sample_count,
            nv12_pipeline,
            nv12_bind_group_layout,
        }
    }

    /// Get or create cached vertex/index buffers for an object.
    fn get_or_cache_buffers<'a>(
        &self,
        obj_id: ObjectId,
        vertices: &[Vertex],
        indices: &[u32],
        cache: &'a mut HashMap<ObjectId, CachedObjectBuffers>,
    ) -> &'a CachedObjectBuffers {
        cache.entry(obj_id).or_insert_with(|| {
            let vertex_buffer =
                self.gpu
                    .device
                    .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                        label: Some("cached_vertex_buffer"),
                        contents: bytemuck::cast_slice(vertices),
                        usage: wgpu::BufferUsages::VERTEX,
                    });
            let index_buffer =
                self.gpu
                    .device
                    .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                        label: Some("cached_index_buffer"),
                        contents: bytemuck::cast_slice(indices),
                        usage: wgpu::BufferUsages::INDEX,
                    });
            CachedObjectBuffers {
                vertex_buffer,
                index_buffer,
                index_count: indices.len() as u32,
            }
        })
    }

    /// Get or create cached texture bind group for a textured object (uploaded once).
    fn get_or_cache_texture<'a>(
        &self,
        obj_id: ObjectId,
        texture_data: &manimgx_core::scene::TextureData,
        cache: &'a mut HashMap<ObjectId, CachedTextureBindGroup>,
    ) -> &'a CachedTextureBindGroup {
        cache.entry(obj_id).or_insert_with(|| {
            let size = wgpu::Extent3d {
                width: texture_data.width,
                height: texture_data.height,
                depth_or_array_layers: 1,
            };
            let texture = self.gpu.device.create_texture(&wgpu::TextureDescriptor {
                label: Some("text_texture"),
                size,
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba8UnormSrgb,
                usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
                view_formats: &[],
            });
            self.gpu.queue.write_texture(
                wgpu::TexelCopyTextureInfo {
                    texture: &texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                &texture_data.rgba,
                wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(4 * texture_data.width),
                    rows_per_image: Some(texture_data.height),
                },
                size,
            );
            let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
            let sampler = self.gpu.device.create_sampler(&wgpu::SamplerDescriptor {
                label: Some("text_sampler"),
                address_mode_u: wgpu::AddressMode::ClampToEdge,
                address_mode_v: wgpu::AddressMode::ClampToEdge,
                mag_filter: wgpu::FilterMode::Linear,
                min_filter: wgpu::FilterMode::Linear,
                ..Default::default()
            });
            let bind_group =
                self.gpu
                    .device
                    .create_bind_group(&wgpu::BindGroupDescriptor {
                        label: Some("text_texture_bg"),
                        layout: &self.pipelines.texture_bind_group_layout,
                        entries: &[
                            wgpu::BindGroupEntry {
                                binding: 0,
                                resource: wgpu::BindingResource::TextureView(&view),
                            },
                            wgpu::BindGroupEntry {
                                binding: 1,
                                resource: wgpu::BindingResource::Sampler(&sampler),
                            },
                        ],
                    });
            CachedTextureBindGroup {
                _texture: texture,
                _view: view,
                _sampler: sampler,
                bind_group,
            }
        })
    }

    fn wait_for_gpu(&self) {
        self.gpu.device.poll(wgpu::Maintain::Wait);
    }

    /// Encode a render pass into a command encoder.
    /// `output_view` is the resolve target (or direct render target if no MSAA).
    #[allow(clippy::too_many_arguments)]
    fn encode_render_pass(
        &self,
        cmd_encoder: &mut wgpu::CommandEncoder,
        res: &FrameResources,
        output_view: &wgpu::TextureView,
        draw_cmds: &[DrawCmd],
        scene: &Scene,
        object_cache: &mut HashMap<ObjectId, CachedObjectBuffers>,
        texture_cache: &mut HashMap<ObjectId, CachedTextureBindGroup>,
        clear_color: wgpu::Color,
    ) {
        let alignment = res.uniform_alignment;

        // Pre-cache textures for textured objects (must happen outside render pass borrow)
        for cmd in draw_cmds {
            let obj = &scene.objects[cmd.obj_idx];
            if let RenderHint::Textured = &obj.render_hint {
                if let Some(ref tex_data) = obj.texture_data {
                    self.get_or_cache_texture(obj.id, tex_data, texture_cache);
                }
            }
        }

        // Always do hardware MSAA resolve — it's essentially free (dedicated fixed-function silicon).
        // NV12 compute shader reads the resolved 1x output_texture afterwards.
        let mut rp = cmd_encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: None,
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: res.msaa_view.as_ref().unwrap_or(output_view),
                resolve_target: res.msaa_view.as_ref().map(|_| output_view),
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(clear_color),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: &res.depth_view,
                depth_ops: Some(wgpu::Operations {
                    load: wgpu::LoadOp::Clear(1.0),
                    store: wgpu::StoreOp::Store,
                }),
                stencil_ops: None,
            }),
            timestamp_writes: None,
            occlusion_query_set: None,
        });

        rp.set_bind_group(0, &res.camera_bind_group, &[]);

        for cmd in draw_cmds {
            let obj = &scene.objects[cmd.obj_idx];
            let is_textured = matches!(&obj.render_hint, RenderHint::Textured);
            let pipeline = match &obj.render_hint {
                RenderHint::Default => &self.pipelines.default,
                RenderHint::FlatUnlit => &self.pipelines.flat_no_cull,
                RenderHint::Textured => &self.pipelines.textured,
            };
            rp.set_pipeline(pipeline);
            let dynamic_offset = (cmd.uniform_slot * alignment) as u32;
            rp.set_bind_group(1, &res.object_bind_group, &[dynamic_offset]);

            if is_textured {
                if let Some(tex_cached) = texture_cache.get(&obj.id) {
                    rp.set_bind_group(2, &tex_cached.bind_group, &[]);
                }
            }

            let cached =
                self.get_or_cache_buffers(obj.id, &obj.vertices, &obj.indices, object_cache);
            rp.set_vertex_buffer(0, cached.vertex_buffer.slice(..));
            rp.set_index_buffer(cached.index_buffer.slice(..), wgpu::IndexFormat::Uint32);
            rp.draw_indexed(0..cached.index_count, 0, 0..1);
        }
    }

    /// Encode render pass, copy to staging, submit, wait, readback into dst.
    fn render_and_readback(
        &self,
        res: &mut FrameResources,
        draw_cmds: &[DrawCmd],
        scene: &Scene,
        object_cache: &mut HashMap<ObjectId, CachedObjectBuffers>,
        texture_cache: &mut HashMap<ObjectId, CachedTextureBindGroup>,
        clear_color: wgpu::Color,
        dst: &mut Vec<u8>,
    ) {
        let mut cmd_encoder =
            self.gpu
                .device
                .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                    label: Some("frame_encoder"),
                });

        self.encode_render_pass(
            &mut cmd_encoder,
            res,
            &res.output_view,
            draw_cmds,
            scene,
            object_cache,
            texture_cache,
            clear_color,
        );

        cmd_encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &res.output_texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &res.staging_buffer,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(res.padded_bytes_per_row),
                    rows_per_image: Some(res.height),
                },
            },
            wgpu::Extent3d {
                width: res.width,
                height: res.height,
                depth_or_array_layers: 1,
            },
        );

        self.gpu.queue.submit(std::iter::once(cmd_encoder.finish()));
        res.staging_buffer
            .slice(..)
            .map_async(wgpu::MapMode::Read, |_| {});
        self.wait_for_gpu();
        res.read_pixels_into(dst);
    }

    /// Print progress bar to stderr.
    fn print_progress(
        frame_idx: u32,
        total_frames: u32,
        render_start: &std::time::Instant,
        last_progress: &mut std::time::Instant,
    ) {
        if last_progress.elapsed().as_millis() >= 250 || frame_idx == total_frames - 1 {
            let done = frame_idx + 1;
            let elapsed = render_start.elapsed().as_secs_f64();
            let pct = done as f64 / total_frames as f64;
            let fps_now = if elapsed > 0.0 {
                done as f64 / elapsed
            } else {
                0.0
            };
            let eta = if pct > 0.0 {
                elapsed / pct - elapsed
            } else {
                0.0
            };
            let bar_width = 30;
            let filled = (pct * bar_width as f64) as usize;
            let bar: String = "█".repeat(filled) + &"░".repeat(bar_width - filled);
            eprint!(
                "\r  [{}] {:>3.0}% | {}/{} | {:.1}s | ~{:.1}s left | {:.0} fps\x1b[K",
                bar,
                pct * 100.0,
                done,
                total_frames,
                elapsed,
                eta,
                fps_now,
            );
            *last_progress = std::time::Instant::now();
        }
    }

    /// Unified render loop with N-buffering and frame deduplication.
    ///
    /// With `n_buffers=1`: current synchronous behavior (render, readback, repeat).
    /// With `n_buffers=2+`: GPU render of frame K overlaps with staging readback of frame K-1.
    pub fn render_video<W: FrameWriter>(
        &self,
        scene: &mut Scene,
        timeline: &dyn manimgx_core::timeline_eval::TimelineEval,
        writer: &mut W,
        total_frames: u32,
        fps: u32,
        n_buffers: u32,
        use_nv12: bool,
        check_cancelled: &dyn Fn() -> bool,
    ) {
        if total_frames == 0 {
            return;
        }

        let effective_buffers = n_buffers.max(1) as usize;

        let nv12_bgl = if use_nv12 {
            Some(&self.nv12_bind_group_layout)
        } else {
            None
        };

        let resources: Vec<FrameResources> = (0..effective_buffers)
            .map(|_| {
                FrameResources::new(
                    &self.gpu.device,
                    scene.width,
                    scene.height,
                    self.color_format,
                    &self.pipelines.camera_bind_group_layout,
                    &self.pipelines.model_bind_group_layout,
                    scene.objects.len(),
                    self.sample_count,
                    use_nv12,
                    nv12_bgl,
                )
            })
            .collect();
        let mut object_cache: HashMap<ObjectId, CachedObjectBuffers> = HashMap::with_capacity(scene.objects.len());
        let mut texture_cache: HashMap<ObjectId, CachedTextureBindGroup> = HashMap::new();

        let alignment = resources[0].uniform_alignment;
        let uniform_size = std::mem::size_of::<ObjectUniform>();
        let cam_size = std::mem::size_of::<CameraUniform>();
        let pixel_size = if use_nv12 {
            resources[0].nv12_size
        } else {
            resources[0].pixel_size
        };

        let clear_color = wgpu::Color {
            r: srgb_to_linear(scene.background[0]) as f64,
            g: srgb_to_linear(scene.background[1]) as f64,
            b: srgb_to_linear(scene.background[2]) as f64,
            a: scene.background[3] as f64,
        };

        // CPU staging for uniform building and dedup comparison (shared across buffers)
        let mut uniform_staging = vec![0u8; resources[0].uniform_staging.len()];
        let mut prev_cam_bytes = vec![0u8; cam_size];
        let mut prev_uniform_bytes = vec![0u8; uniform_staging.len()];
        let mut prev_draw_count: usize = 0;
        let mut first_frame = true;
        let mut dup_count = 0u32;
        let mut render_count = 0usize;
        let mut pixel_buf = vec![0u8; pixel_size];

        // Pending readback queue: buffer indices with submitted but not-yet-read staging data
        let mut pending: std::collections::VecDeque<usize> = std::collections::VecDeque::new();

        // Pre-allocate draw command buffer (reused each frame)
        let mut draw_cmds: Vec<DrawCmd> = Vec::with_capacity(scene.objects.len());

        let render_start = std::time::Instant::now();
        let mut last_progress = std::time::Instant::now();

        for frame_idx in 0..total_frames {
            Self::print_progress(frame_idx, total_frames, &render_start, &mut last_progress);
            if check_cancelled() { eprintln!("\n  Render interrupted at frame {}/{}", frame_idx, total_frames); break; }

            let time = frame_idx as f32 / fps as f32;
            timeline.evaluate(scene, time);

            let view_proj = scene.camera.view_projection_matrix(scene.aspect_ratio());
            let cam_uniform = CameraUniform {
                view_proj: view_proj.to_cols_array_2d(),
            };
            let cam_bytes = bytemuck::bytes_of(&cam_uniform);

            // Build draw commands + object uniforms into shared staging buffer
            draw_cmds.clear();
            for (obj_idx, obj) in scene.objects.iter().enumerate() {
                if obj.material.opacity <= 0.0 {
                    continue;
                }
                let slot = draw_cmds.len();
                let byte_offset = slot * alignment;
                let mut material_color = obj.material.color;
                material_color[3] = obj.material.color[3] * obj.material.opacity;
                let uniform = ObjectUniform {
                    model: obj.transform.to_matrix().to_cols_array_2d(),
                    material_color,
                    use_vertex_colors: if obj.material.use_vertex_colors { 1 } else { 0 },
                    _pad: [0; 3],
                };
                uniform_staging[byte_offset..byte_offset + uniform_size]
                    .copy_from_slice(bytemuck::bytes_of(&uniform));
                draw_cmds.push(DrawCmd {
                    obj_idx,
                    uniform_slot: slot,
                });
            }

            let total_uniform_bytes = draw_cmds.len() * alignment;

            // Frame deduplication: skip GPU render when scene state is unchanged
            let is_dup = !first_frame
                && draw_cmds.len() == prev_draw_count
                && cam_bytes == &prev_cam_bytes[..]
                && (total_uniform_bytes == 0
                    || uniform_staging[..total_uniform_bytes]
                        == prev_uniform_bytes[..total_uniform_bytes]);

            if is_dup {
                writer.write_duplicate();
                dup_count += 1;
                continue;
            }

            let buf_idx = render_count % effective_buffers;

            {
                // Staging readback path with N-buffering
                // Drain oldest pending readback if all buffers are in use
                if pending.len() >= effective_buffers {
                    let drain_idx = pending.pop_front().unwrap();
                    self.wait_for_gpu();
                    if use_nv12 {
                        resources[drain_idx].read_nv12_into(&mut pixel_buf);
                    } else {
                        resources[drain_idx].read_pixels_into(&mut pixel_buf);
                    }
                    writer.write_frame(&pixel_buf);
                }

                let res = &resources[buf_idx];
                self.gpu
                    .queue
                    .write_buffer(&res.camera_buffer, 0, cam_bytes);
                if total_uniform_bytes > 0 {
                    self.gpu.queue.write_buffer(
                        &res.object_uniform_buffer,
                        0,
                        &uniform_staging[..total_uniform_bytes],
                    );
                }

                // Encode render pass + copy to staging + submit (don't wait yet)
                let mut cmd_encoder =
                    self.gpu
                        .device
                        .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                            label: Some("frame_encoder"),
                        });
                self.encode_render_pass(
                    &mut cmd_encoder,
                    res,
                    &res.output_view,
                    &draw_cmds,
                    scene,
                    &mut object_cache,
                    &mut texture_cache,
                    clear_color,
                );

                if use_nv12 {
                    // Compute pass: MSAA resolve + NV12 conversion
                    {
                        let mut cpass = cmd_encoder.begin_compute_pass(
                            &wgpu::ComputePassDescriptor {
                                label: Some("nv12_convert"),
                                timestamp_writes: None,
                            },
                        );
                        cpass.set_pipeline(&self.nv12_pipeline);
                        cpass.set_bind_group(0, res.nv12_bind_group.as_ref().unwrap(), &[]);
                        cpass.dispatch_workgroups(
                            res.width.div_ceil(32),
                            res.height.div_ceil(16),
                            1,
                        );
                    }
                    // Copy storage → staging
                    let nv12_sz = res.nv12_size as u64;
                    cmd_encoder.copy_buffer_to_buffer(
                        res.nv12_storage_buffer.as_ref().unwrap(),
                        0,
                        res.nv12_staging_buffer.as_ref().unwrap(),
                        0,
                        nv12_sz,
                    );
                    self.gpu.queue.submit(std::iter::once(cmd_encoder.finish()));
                    res.nv12_staging_buffer
                        .as_ref()
                        .unwrap()
                        .slice(..)
                        .map_async(wgpu::MapMode::Read, |_| {});
                } else {
                    cmd_encoder.copy_texture_to_buffer(
                        wgpu::TexelCopyTextureInfo {
                            texture: &res.output_texture,
                            mip_level: 0,
                            origin: wgpu::Origin3d::ZERO,
                            aspect: wgpu::TextureAspect::All,
                        },
                        wgpu::TexelCopyBufferInfo {
                            buffer: &res.staging_buffer,
                            layout: wgpu::TexelCopyBufferLayout {
                                offset: 0,
                                bytes_per_row: Some(res.padded_bytes_per_row),
                                rows_per_image: Some(res.height),
                            },
                        },
                        wgpu::Extent3d {
                            width: res.width,
                            height: res.height,
                            depth_or_array_layers: 1,
                        },
                    );
                    self.gpu.queue.submit(std::iter::once(cmd_encoder.finish()));
                    // Issue map_async immediately — overlap GPU work with CPU readback of previous frames
                    res.staging_buffer
                        .slice(..)
                        .map_async(wgpu::MapMode::Read, |_| {});
                }
                pending.push_back(buf_idx);
            }

            // Update dedup state
            prev_cam_bytes.copy_from_slice(cam_bytes);
            if total_uniform_bytes > 0 {
                prev_uniform_bytes[..total_uniform_bytes]
                    .copy_from_slice(&uniform_staging[..total_uniform_bytes]);
            }
            prev_draw_count = draw_cmds.len();
            first_frame = false;
            render_count += 1;
        }

        // Drain remaining pending readbacks
        while let Some(drain_idx) = pending.pop_front() {
            self.wait_for_gpu();
            if use_nv12 {
                resources[drain_idx].read_nv12_into(&mut pixel_buf);
            } else {
                resources[drain_idx].read_pixels_into(&mut pixel_buf);
            }
            writer.write_frame(&pixel_buf);
        }

        writer.finish();

        eprintln!();
        let rendered = total_frames - dup_count;
        eprintln!(
            "  frames: {} rendered, {} duplicates skipped ({:.0}%)",
            rendered,
            dup_count,
            dup_count as f64 / total_frames as f64 * 100.0,
        );
    }

    /// Render video using in-process x264 encoding with CPU-side NV12 buffer pool.
    ///
    /// GPU renders → NV12 compute → staging readback → pool Vec<u8> → x264 encoder thread.
    /// No ffmpeg subprocess. Pool buffers are pinned (never reallocated) so raw pointers
    /// sent to the encoder thread remain valid.
    #[allow(clippy::too_many_arguments)]
    pub fn render_video_x264(
        &self,
        scene: &mut Scene,
        timeline: &dyn manimgx_core::timeline_eval::TimelineEval,
        output: &str,
        total_frames: u32,
        fps: u32,
        n_buffers: u32,
        preset: &str,
        crf: u32,
        muxer: &str,
        check_cancelled: &dyn Fn() -> bool,
    ) {
        use manimgx_encode::{X264FrameMsg, X264Writer};
        use std::collections::VecDeque;
        use std::sync::mpsc;

        if total_frames == 0 {
            return;
        }

        let n = n_buffers.max(1) as usize;
        let w = scene.width;
        let h = scene.height;
        let nv12_size = (w * h * 3 / 2) as usize;

        let nv12_bgl = Some(&self.nv12_bind_group_layout);

        let resources: Vec<FrameResources> = (0..n)
            .map(|_| {
                FrameResources::new(
                    &self.gpu.device,
                    w,
                    h,
                    self.color_format,
                    &self.pipelines.camera_bind_group_layout,
                    &self.pipelines.model_bind_group_layout,
                    scene.objects.len(),
                    self.sample_count,
                    true,
                    nv12_bgl,
                )
            })
            .collect();
        let mut object_cache: HashMap<ObjectId, CachedObjectBuffers> = HashMap::with_capacity(scene.objects.len());
        let mut texture_cache: HashMap<ObjectId, CachedTextureBindGroup> = HashMap::new();

        let alignment = resources[0].uniform_alignment;
        let uniform_size = std::mem::size_of::<ObjectUniform>();
        let cam_size = std::mem::size_of::<CameraUniform>();

        // CPU-side NV12 buffer pool (elastic, decoupled from GPU slots)
        let pool_count = 8usize;
        let (release_tx, release_rx) = mpsc::channel::<usize>();
        let mut pool_buffers: Vec<Vec<u8>> = (0..pool_count).map(|_| vec![0u8; nv12_size]).collect();
        let mut pool_available: VecDeque<usize> = (0..pool_count).collect();

        // In-process x264 encoder (spawns encoder thread)
        let writer = X264Writer::new(output, w, h, fps, preset, crf, release_tx, muxer);

        let clear_color = wgpu::Color {
            r: srgb_to_linear(scene.background[0]) as f64,
            g: srgb_to_linear(scene.background[1]) as f64,
            b: srgb_to_linear(scene.background[2]) as f64,
            a: scene.background[3] as f64,
        };

        // CPU staging for uniform building and dedup comparison
        let mut uniform_staging = vec![0u8; resources[0].uniform_staging.len()];
        let mut prev_cam_bytes = vec![0u8; cam_size];
        let mut prev_uniform_bytes = vec![0u8; uniform_staging.len()];
        let mut prev_draw_count: usize = 0;
        let mut first_frame = true;
        let mut dup_count = 0u32;
        let mut render_count = 0usize;

        // N-buffering: pending queue tracks (gpu_slot_idx, pool_buf_idx)
        let mut pending: VecDeque<(usize, usize)> = VecDeque::new();

        // Pre-allocate draw command buffer (reused each frame)
        let mut draw_cmds: Vec<DrawCmd> = Vec::with_capacity(scene.objects.len());

        let render_start = std::time::Instant::now();
        let mut last_progress = std::time::Instant::now();

        // Helper: acquire a pool buffer index
        let acquire_pool = |available: &mut VecDeque<usize>, rx: &mpsc::Receiver<usize>| -> usize {
            // Drain all released buffers (non-blocking)
            while let Ok(idx) = rx.try_recv() {
                available.push_back(idx);
            }
            if let Some(idx) = available.pop_front() {
                return idx;
            }
            // Pool exhausted — block until encoder releases one
            rx.recv().expect("x264 encoder thread died")
        };

        for frame_idx in 0..total_frames {
            Self::print_progress(frame_idx, total_frames, &render_start, &mut last_progress);
            if check_cancelled() {
                eprintln!("\n  Render interrupted at frame {}/{}", frame_idx, total_frames);
                break;
            }

            let time = frame_idx as f32 / fps as f32;
            timeline.evaluate(scene, time);

            let view_proj = scene.camera.view_projection_matrix(scene.aspect_ratio());
            let cam_uniform = CameraUniform {
                view_proj: view_proj.to_cols_array_2d(),
            };
            let cam_bytes = bytemuck::bytes_of(&cam_uniform);

            // Build draw commands + object uniforms
            draw_cmds.clear();
            for (obj_idx, obj) in scene.objects.iter().enumerate() {
                if obj.material.opacity <= 0.0 {
                    continue;
                }
                let slot = draw_cmds.len();
                let byte_offset = slot * alignment;
                let mut material_color = obj.material.color;
                material_color[3] = obj.material.color[3] * obj.material.opacity;
                let uniform = ObjectUniform {
                    model: obj.transform.to_matrix().to_cols_array_2d(),
                    material_color,
                    use_vertex_colors: if obj.material.use_vertex_colors { 1 } else { 0 },
                    _pad: [0; 3],
                };
                uniform_staging[byte_offset..byte_offset + uniform_size]
                    .copy_from_slice(bytemuck::bytes_of(&uniform));
                draw_cmds.push(DrawCmd {
                    obj_idx,
                    uniform_slot: slot,
                });
            }

            let total_uniform_bytes = draw_cmds.len() * alignment;

            // Frame deduplication
            let is_dup = !first_frame
                && draw_cmds.len() == prev_draw_count
                && cam_bytes == &prev_cam_bytes[..]
                && (total_uniform_bytes == 0
                    || uniform_staging[..total_uniform_bytes]
                        == prev_uniform_bytes[..total_uniform_bytes]);

            if is_dup {
                // Drain ALL pending GPU slots before encoding dup
                while let Some((drain_slot, drain_buf)) = pending.pop_front() {
                    self.wait_for_gpu();
                    resources[drain_slot].read_nv12_into_slice(&mut pool_buffers[drain_buf]);

                    writer.send(X264FrameMsg::Frame {
                        ptr: pool_buffers[drain_buf].as_ptr(),
                        len: nv12_size,
                        pts: (frame_idx as i64) - (pending.len() as i64) - 1,
                        buf_idx: drain_buf,
                    });
                }

                writer.send(X264FrameMsg::Dup {
                    pts: frame_idx as i64,
                });
                dup_count += 1;
                continue;
            }

            let slot_idx = render_count % n;

            // Drain oldest pending slot if all GPU slots are in use
            if pending.len() >= n {
                let (drain_slot, drain_buf) = pending.pop_front().unwrap();
                self.wait_for_gpu();
                resources[drain_slot].read_nv12_into_slice(&mut pool_buffers[drain_buf]);

                writer.send(X264FrameMsg::Frame {
                    ptr: pool_buffers[drain_buf].as_ptr(),
                    len: nv12_size,
                    pts: (frame_idx as i64) - (n as i64),
                    buf_idx: drain_buf,
                });
            }

            // Acquire a pool buffer for NV12 output
            let buf_idx = acquire_pool(&mut pool_available, &release_rx);

            // Write uniforms to GPU
            let res = &resources[slot_idx];
            self.gpu
                .queue
                .write_buffer(&res.camera_buffer, 0, cam_bytes);
            if total_uniform_bytes > 0 {
                self.gpu.queue.write_buffer(
                    &res.object_uniform_buffer,
                    0,
                    &uniform_staging[..total_uniform_bytes],
                );
            }

            // Encode render pass + NV12 compute + staging copy + submit
            let mut cmd_encoder =
                self.gpu
                    .device
                    .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                        label: Some("x264_frame"),
                    });
            self.encode_render_pass(
                &mut cmd_encoder,
                res,
                &res.output_view,
                &draw_cmds,
                scene,
                &mut object_cache,
                &mut texture_cache,
                clear_color,
            );

            // NV12 compute pass
            {
                let mut cpass = cmd_encoder.begin_compute_pass(
                    &wgpu::ComputePassDescriptor {
                        label: Some("nv12_convert"),
                        timestamp_writes: None,
                    },
                );
                cpass.set_pipeline(&self.nv12_pipeline);
                cpass.set_bind_group(0, res.nv12_bind_group.as_ref().unwrap(), &[]);
                cpass.dispatch_workgroups(
                    res.width.div_ceil(32),
                    res.height.div_ceil(16),
                    1,
                );
            }
            // Copy storage → staging
            let nv12_sz = res.nv12_size as u64;
            cmd_encoder.copy_buffer_to_buffer(
                res.nv12_storage_buffer.as_ref().unwrap(),
                0,
                res.nv12_staging_buffer.as_ref().unwrap(),
                0,
                nv12_sz,
            );
            self.gpu.queue.submit(std::iter::once(cmd_encoder.finish()));
            res.nv12_staging_buffer
                .as_ref()
                .unwrap()
                .slice(..)
                .map_async(wgpu::MapMode::Read, |_| {});

            pending.push_back((slot_idx, buf_idx));

            // Update dedup state
            prev_cam_bytes.copy_from_slice(cam_bytes);
            if total_uniform_bytes > 0 {
                prev_uniform_bytes[..total_uniform_bytes]
                    .copy_from_slice(&uniform_staging[..total_uniform_bytes]);
            }
            prev_draw_count = draw_cmds.len();
            first_frame = false;
            render_count += 1;
        }

        // Drain remaining pending slots
        let remaining = pending.len();
        let mut drain_count = 0;
        while let Some((drain_slot, drain_buf)) = pending.pop_front() {
            self.wait_for_gpu();
            resources[drain_slot].read_nv12_into_slice(&mut pool_buffers[drain_buf]);

            writer.send(X264FrameMsg::Frame {
                ptr: pool_buffers[drain_buf].as_ptr(),
                len: nv12_size,
                pts: (total_frames as i64) - (remaining as i64) + (drain_count as i64),
                buf_idx: drain_buf,
            });
            drain_count += 1;
        }

        // Flush encoder, join thread, finalize MP4
        writer.finish();

        eprintln!();
        let rendered = total_frames - dup_count;
        eprintln!(
            "  frames: {} rendered, {} duplicates skipped ({:.0}%)",
            rendered,
            dup_count,
            dup_count as f64 / total_frames as f64 * 100.0,
        );
    }

    /// Render a single frame, returning RGBA pixel data (used for PNG export).
    pub fn render_frame(&self, scene: &Scene) -> Vec<u8> {
        let mut res = FrameResources::new(
            &self.gpu.device,
            scene.width,
            scene.height,
            self.color_format,
            &self.pipelines.camera_bind_group_layout,
            &self.pipelines.model_bind_group_layout,
            scene.objects.len(),
            self.sample_count,
            false,
            None,
        );
        let mut object_cache: HashMap<ObjectId, CachedObjectBuffers> = HashMap::with_capacity(scene.objects.len());
        let mut texture_cache: HashMap<ObjectId, CachedTextureBindGroup> = HashMap::new();

        // Camera
        let view_proj = scene.camera.view_projection_matrix(scene.aspect_ratio());
        let camera_uniform = CameraUniform {
            view_proj: view_proj.to_cols_array_2d(),
        };
        self.gpu.queue.write_buffer(
            &res.camera_buffer,
            0,
            bytemuck::cast_slice(&[camera_uniform]),
        );

        // Object uniforms
        let alignment = res.uniform_alignment;
        let uniform_size = std::mem::size_of::<ObjectUniform>();
        let mut draw_cmds: Vec<DrawCmd> = Vec::with_capacity(scene.objects.len());

        for (obj_idx, obj) in scene.objects.iter().enumerate() {
            if obj.material.opacity <= 0.0 {
                continue;
            }
            let slot = draw_cmds.len();
            let offset = slot * alignment;
            let mut material_color = obj.material.color;
            material_color[3] = obj.material.color[3] * obj.material.opacity;
            let uniform = ObjectUniform {
                model: obj.transform.to_matrix().to_cols_array_2d(),
                material_color,
                use_vertex_colors: if obj.material.use_vertex_colors { 1 } else { 0 },
                _pad: [0; 3],
            };
            res.uniform_staging[offset..offset + uniform_size]
                .copy_from_slice(bytemuck::bytes_of(&uniform));
            draw_cmds.push(DrawCmd {
                obj_idx,
                uniform_slot: slot,
            });
        }

        if !draw_cmds.is_empty() {
            let total_bytes = draw_cmds.len() * alignment;
            self.gpu.queue.write_buffer(
                &res.object_uniform_buffer,
                0,
                &res.uniform_staging[..total_bytes],
            );
        }

        let clear_color = wgpu::Color {
            r: srgb_to_linear(scene.background[0]) as f64,
            g: srgb_to_linear(scene.background[1]) as f64,
            b: srgb_to_linear(scene.background[2]) as f64,
            a: scene.background[3] as f64,
        };

        let mut pixels = Vec::with_capacity(res.pixel_size);
        self.render_and_readback(
            &mut res,
            &draw_cmds,
            scene,
            &mut object_cache,
            &mut texture_cache,
            clear_color,
            &mut pixels,
        );
        pixels
    }

    /// Render a single frame and save as PNG (requires `png_debug` feature).
    #[cfg(feature = "png_debug")]
    pub fn render_to_png(&self, scene: &Scene, path: &str) {
        let pixels = self.render_frame(scene);
        let img = image::RgbaImage::from_raw(scene.width, scene.height, pixels)
            .expect("Invalid image data");
        img.save(path).expect("Failed to save PNG");
        log::info!("Saved PNG: {}", path);
    }

    /// Stub when `png_debug` is not enabled — panics with a clear message.
    #[cfg(not(feature = "png_debug"))]
    pub fn render_to_png(&self, _scene: &Scene, _path: &str) {
        panic!("render_to_png requires the `png_debug` feature on manimgx-render");
    }
}
