use metal::*;
use pyo3::prelude::*;
use std::collections::VecDeque;
use std::ffi::c_void;

use crate::common::*;
use crate::render_context::{ACTIVE, FRAME_INDEX, OPACITY, POSITION_X, SIDE, STRIDE, Z_INDEX};
use crate::tessellation::{Mesh, Texture as TexData};

struct MetalGpuMesh {
    vertex_buffer: Buffer,
    index_buffer: Buffer,
    index_count: u64,
    mobject_id: u32,
    mesh_index: usize,
    cached_generation: u32,
}

struct MetalGpuTexturedMesh {
    vertex_buffer: Buffer,
    index_buffer: Buffer,
    index_count: u64,
    textures: Vec<Texture>,
    sampler_state: SamplerState,
    mobject_id: u32,
    frame_count: u32,
}

#[pyclass]
pub struct MetalRenderer {
    device: Device,
    queue: CommandQueue,
    pipeline: RenderPipelineState,
    ds_state: DepthStencilState,
    msaa_texture: Texture,
    depth_texture: Texture,
    // NV12 compute conversion (for video output)
    nv12_pipeline: ComputePipelineState,
    nv12_buffers: [Buffer; PIPELINE_DEPTH],
    nv12_frame_size: u64,
    // RGBA resolve (for image sequence output — avoids NV12 chroma subsampling)
    resolve_texture: Texture,
    rgba_buffers: [Buffer; PIPELINE_DEPTH],
    rgba_frame_size: u64,
    // Shared state
    camera_uniforms: CameraUniforms,
    width: u32,
    height: u32,
    gpu_meshes: Vec<MetalGpuMesh>,
    // Textured pipeline
    textured_pipeline: RenderPipelineState,
    gpu_textured_meshes: Vec<MetalGpuTexturedMesh>,
    num_mobjects: u32,
    background_color: [f32; 4],
    warmup_done: bool,
}

#[pymethods]
impl MetalRenderer {
    #[new]
    pub fn new(width: u32, height: u32) -> PyResult<Self> {
        let device = Device::system_default()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err("No Metal device found"))?;

        let queue = device.new_command_queue();

        let shader_source = include_str!("shaders/main.metal");
        let options = CompileOptions::new();
        let library = device
            .new_library_with_source(shader_source, &options)
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!("MSL compile error: {e}"))
            })?;

        let vertex_fn = library.get_function("vs_main", None).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to get vertex function: {e}"))
        })?;

        let fragment_fn = library.get_function("fs_main", None).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!(
                "Failed to get fragment function: {e}"
            ))
        })?;

        // Vertex descriptor: position (float3) + normal (float3) + uv (float2) + color (float4) at buffer index 2
        // Morph target: position (float3) + normal (float3) + uv (float2) + color (float4) at buffer index 3
        // (indices 0 and 1 are used for DrawUniforms and CameraUniforms via set_vertex_bytes)
        let vertex_desc = VertexDescriptor::new();

        let attr0 = vertex_desc.attributes().object_at(0).unwrap();
        attr0.set_format(MTLVertexFormat::Float3);
        attr0.set_offset(0);
        attr0.set_buffer_index(2);

        let attr1 = vertex_desc.attributes().object_at(1).unwrap();
        attr1.set_format(MTLVertexFormat::Float3);
        attr1.set_offset(12);
        attr1.set_buffer_index(2);

        let attr2 = vertex_desc.attributes().object_at(2).unwrap();
        attr2.set_format(MTLVertexFormat::Float2);
        attr2.set_offset(24);
        attr2.set_buffer_index(2);

        let attr3 = vertex_desc.attributes().object_at(3).unwrap();
        attr3.set_format(MTLVertexFormat::Float4);
        attr3.set_offset(32);
        attr3.set_buffer_index(2);

        let layout = vertex_desc.layouts().object_at(2).unwrap();
        layout.set_stride(std::mem::size_of::<Vertex>() as u64);
        layout.set_step_function(MTLVertexStepFunction::PerVertex);
        layout.set_step_rate(1);

        let pipeline_desc = RenderPipelineDescriptor::new();
        pipeline_desc.set_vertex_function(Some(&vertex_fn));
        pipeline_desc.set_fragment_function(Some(&fragment_fn));
        pipeline_desc.set_vertex_descriptor(Some(vertex_desc));
        pipeline_desc.set_sample_count(MSAA_SAMPLES as u64);
        pipeline_desc.set_depth_attachment_pixel_format(MTLPixelFormat::Depth32Float);

        let color_att = pipeline_desc.color_attachments().object_at(0).unwrap();
        color_att.set_pixel_format(MTLPixelFormat::RGBA8Unorm);
        color_att.set_blending_enabled(true);
        color_att.set_rgb_blend_operation(MTLBlendOperation::Add);
        color_att.set_alpha_blend_operation(MTLBlendOperation::Add);
        color_att.set_source_rgb_blend_factor(MTLBlendFactor::SourceAlpha);
        color_att.set_destination_rgb_blend_factor(MTLBlendFactor::OneMinusSourceAlpha);
        color_att.set_source_alpha_blend_factor(MTLBlendFactor::One);
        color_att.set_destination_alpha_blend_factor(MTLBlendFactor::OneMinusSourceAlpha);

        let pipeline = device
            .new_render_pipeline_state(&pipeline_desc)
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to create pipeline: {e}"))
            })?;

        // Textured pipeline
        let tex_shader_source = include_str!("shaders/textured.metal");
        let tex_library = device
            .new_library_with_source(tex_shader_source, &options)
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "Textured MSL compile error: {e}"
                ))
            })?;

        let tex_vertex_fn = tex_library.get_function("vs_textured", None).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!(
                "Failed to get textured vertex function: {e}"
            ))
        })?;

        let tex_fragment_fn = tex_library.get_function("fs_textured", None).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!(
                "Failed to get textured fragment function: {e}"
            ))
        })?;

        // Vertex descriptor: position (float3) + uv (float2) at buffer index 30
        let tex_vertex_desc = VertexDescriptor::new();

        let tex_attr0 = tex_vertex_desc.attributes().object_at(0).unwrap();
        tex_attr0.set_format(MTLVertexFormat::Float3);
        tex_attr0.set_offset(0);
        tex_attr0.set_buffer_index(2);

        let tex_attr1 = tex_vertex_desc.attributes().object_at(1).unwrap();
        tex_attr1.set_format(MTLVertexFormat::Float2);
        tex_attr1.set_offset(12);
        tex_attr1.set_buffer_index(2);

        let tex_layout = tex_vertex_desc.layouts().object_at(2).unwrap();
        tex_layout.set_stride(std::mem::size_of::<TexturedVertex>() as u64);
        tex_layout.set_step_function(MTLVertexStepFunction::PerVertex);
        tex_layout.set_step_rate(1);

        let tex_pipeline_desc = RenderPipelineDescriptor::new();
        tex_pipeline_desc.set_vertex_function(Some(&tex_vertex_fn));
        tex_pipeline_desc.set_fragment_function(Some(&tex_fragment_fn));
        tex_pipeline_desc.set_vertex_descriptor(Some(tex_vertex_desc));
        tex_pipeline_desc.set_sample_count(MSAA_SAMPLES as u64);
        tex_pipeline_desc.set_depth_attachment_pixel_format(MTLPixelFormat::Depth32Float);

        let tex_color_att = tex_pipeline_desc.color_attachments().object_at(0).unwrap();
        tex_color_att.set_pixel_format(MTLPixelFormat::RGBA8Unorm);
        tex_color_att.set_blending_enabled(true);
        tex_color_att.set_rgb_blend_operation(MTLBlendOperation::Add);
        tex_color_att.set_alpha_blend_operation(MTLBlendOperation::Add);
        tex_color_att.set_source_rgb_blend_factor(MTLBlendFactor::SourceAlpha);
        tex_color_att.set_destination_rgb_blend_factor(MTLBlendFactor::OneMinusSourceAlpha);
        tex_color_att.set_source_alpha_blend_factor(MTLBlendFactor::One);
        tex_color_att.set_destination_alpha_blend_factor(MTLBlendFactor::OneMinusSourceAlpha);

        let textured_pipeline = device
            .new_render_pipeline_state(&tex_pipeline_desc)
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "Failed to create textured pipeline: {e}"
                ))
            })?;

        // Depth-stencil state: depth LessEqual, write enabled
        let ds_desc = DepthStencilDescriptor::new();
        ds_desc.set_depth_compare_function(MTLCompareFunction::LessEqual);
        ds_desc.set_depth_write_enabled(true);
        let ds_state = device.new_depth_stencil_state(&ds_desc);

        // MSAA texture — ShaderRead lets NV12 compute read samples directly
        let msaa_desc = TextureDescriptor::new();
        msaa_desc.set_texture_type(MTLTextureType::D2Multisample);
        msaa_desc.set_pixel_format(MTLPixelFormat::RGBA8Unorm);
        msaa_desc.set_width(width as u64);
        msaa_desc.set_height(height as u64);
        msaa_desc.set_sample_count(MSAA_SAMPLES as u64);
        msaa_desc.set_storage_mode(MTLStorageMode::Private);
        msaa_desc.set_usage(MTLTextureUsage::RenderTarget | MTLTextureUsage::ShaderRead);
        let msaa_texture = device.new_texture(&msaa_desc);

        // Depth texture (MSAA)
        let depth_tex_desc = TextureDescriptor::new();
        depth_tex_desc.set_texture_type(MTLTextureType::D2Multisample);
        depth_tex_desc.set_pixel_format(MTLPixelFormat::Depth32Float);
        depth_tex_desc.set_width(width as u64);
        depth_tex_desc.set_height(height as u64);
        depth_tex_desc.set_sample_count(MSAA_SAMPLES as u64);
        depth_tex_desc.set_storage_mode(MTLStorageMode::Private);
        depth_tex_desc.set_usage(MTLTextureUsage::RenderTarget);
        let depth_texture = device.new_texture(&depth_tex_desc);

        // NV12 compute pipeline
        let nv12_source = include_str!("shaders/nv12_convert.metal");
        let nv12_library = device
            .new_library_with_source(nv12_source, &options)
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!("NV12 MSL compile error: {e}"))
            })?;

        let nv12_fn = nv12_library
            .get_function("nv12_convert", None)
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "Failed to get nv12_convert function: {e}"
                ))
            })?;

        let nv12_pipeline = device
            .new_compute_pipeline_state_with_function(&nv12_fn)
            .map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!(
                    "Failed to create NV12 compute pipeline: {e}"
                ))
            })?;

        // NV12 output buffers (shared, zero-copy readback)
        let nv12_frame_size = (width as u64 * height as u64 * 3) / 2;
        let nv12_buffers: [Buffer; PIPELINE_DEPTH] = std::array::from_fn(|_| {
            device.new_buffer(nv12_frame_size, MTLResourceOptions::StorageModeShared)
        });

        // RGBA resolve texture + staging buffers (for image sequence output)
        let resolve_desc = TextureDescriptor::new();
        resolve_desc.set_texture_type(MTLTextureType::D2);
        resolve_desc.set_pixel_format(MTLPixelFormat::RGBA8Unorm);
        resolve_desc.set_width(width as u64);
        resolve_desc.set_height(height as u64);
        resolve_desc.set_storage_mode(MTLStorageMode::Private);
        resolve_desc.set_usage(MTLTextureUsage::RenderTarget);
        let resolve_texture = device.new_texture(&resolve_desc);

        let rgba_frame_size = width as u64 * height as u64 * 4;
        let rgba_buffers: [Buffer; PIPELINE_DEPTH] = std::array::from_fn(|_| {
            device.new_buffer(rgba_frame_size, MTLResourceOptions::StorageModeShared)
        });

        // Initialize with defaults — will be overwritten on first frame
        let camera_uniforms = CameraUniforms {
            view_projection: orthographic_projection(width, height, 8.0),
        };
        let background_color = [0.0, 0.0, 0.0, 1.0];

        Ok(MetalRenderer {
            device,
            queue,
            pipeline,
            ds_state,
            msaa_texture,
            depth_texture,
            nv12_pipeline,
            nv12_buffers,
            nv12_frame_size,
            resolve_texture,
            rgba_buffers,
            rgba_frame_size,
            camera_uniforms,
            width,
            height,
            gpu_meshes: Vec::new(),
            textured_pipeline,
            gpu_textured_meshes: Vec::new(),
            num_mobjects: 0,
            background_color,
            warmup_done: false,
        })
    }
}

impl MetalRenderer {
    pub(crate) fn upload_meshes(
        &mut self,
        meshes: Vec<Mesh>,
        textures: &[Option<TexData>],
        mobject_ids: Vec<u32>,
        num_mobjects: u32,
    ) {
        self.gpu_meshes.clear();
        self.gpu_textured_meshes.clear();
        self.num_mobjects = num_mobjects;

        for (geo_idx, (geo, &mobject_id)) in meshes.iter().zip(mobject_ids.iter()).enumerate() {
            if let Some(tex) = textures.get(geo_idx).and_then(|t| t.as_ref()) {
                // Textured mesh path
                let vertices = build_textured_vertices(geo);
                let vertex_data = bytemuck::cast_slice::<TexturedVertex, u8>(&vertices);
                let index_data = bytemuck::cast_slice::<u32, u8>(&geo.texture_indices);

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

                // Create a GPU texture for each frame
                let mut textures = Vec::with_capacity(tex.frames.len());
                for frame_data in &tex.frames {
                    let tex_desc = TextureDescriptor::new();
                    tex_desc.set_texture_type(MTLTextureType::D2);
                    tex_desc.set_pixel_format(MTLPixelFormat::RGBA8Unorm);
                    tex_desc.set_width(tex.width as u64);
                    tex_desc.set_height(tex.height as u64);
                    tex_desc.set_storage_mode(MTLStorageMode::Shared);
                    tex_desc.set_usage(MTLTextureUsage::ShaderRead);
                    let gpu_tex = self.device.new_texture(&tex_desc);

                    let region = MTLRegion {
                        origin: MTLOrigin { x: 0, y: 0, z: 0 },
                        size: MTLSize {
                            width: tex.width as u64,
                            height: tex.height as u64,
                            depth: 1,
                        },
                    };
                    let bytes_per_row = tex.width as u64 * 4;
                    gpu_tex.replace_region(
                        region,
                        0,
                        frame_data.as_ptr() as *const c_void,
                        bytes_per_row,
                    );
                    textures.push(gpu_tex);
                }

                // Create sampler
                let sampler_desc = SamplerDescriptor::new();
                sampler_desc.set_min_filter(MTLSamplerMinMagFilter::Linear);
                sampler_desc.set_mag_filter(MTLSamplerMinMagFilter::Linear);
                sampler_desc.set_address_mode_s(MTLSamplerAddressMode::ClampToEdge);
                sampler_desc.set_address_mode_t(MTLSamplerAddressMode::ClampToEdge);
                let sampler_state = self.device.new_sampler(&sampler_desc);

                self.gpu_textured_meshes.push(MetalGpuTexturedMesh {
                    vertex_buffer,
                    index_buffer,
                    index_count: geo.texture_indices.len() as u64,
                    textures,
                    sampler_state,
                    mobject_id,
                    frame_count: tex.frames.len() as u32,
                });
                continue;
            }

            // Solid mesh path
            for submesh in geo.submeshes.iter() {
                if submesh.indices.is_empty() {
                    continue;
                }

                let vertices = build_vertices(submesh);
                let vertex_data = bytemuck::cast_slice::<Vertex, u8>(&vertices);
                let index_data = bytemuck::cast_slice::<u32, u8>(&submesh.indices);

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

                self.gpu_meshes.push(MetalGpuMesh {
                    vertex_buffer,
                    index_buffer,
                    index_count: submesh.indices.len() as u64,
                    mobject_id,
                    mesh_index: mobject_id as usize,
                    cached_generation: 0,
                });
            }
        }
    }
}

impl MetalRenderer {
    pub(crate) fn render_all_frames(
        &mut self,
        py: Python<'_>,
        evaluate_frame: &Py<PyAny>,
        surface_refs: &[Py<crate::tessellation::Surface>],
        object3d_refs: &[Py<crate::scene_node::Object3D>],
        camera_ref: &Py<crate::camera::Camera>,
        cfg: RenderConfig,
    ) -> PyResult<()> {
        self.render_loop(
            py,
            evaluate_frame,
            surface_refs,
            object3d_refs,
            camera_ref,
            &cfg,
        )
        .map_err(pyo3::exceptions::PyRuntimeError::new_err)
    }

    fn sync_dirty_surfaces(
        &mut self,
        py: Python<'_>,
        surface_refs: &[Py<crate::tessellation::Surface>],
    ) {
        for gpu_mesh in &mut self.gpu_meshes {
            let surface = surface_refs[gpu_mesh.mesh_index].borrow(py);
            if surface.generation != gpu_mesh.cached_generation {
                let geo = surface.mesh.borrow(py);
                // Find a non-empty submesh to re-upload
                for submesh in &geo.submeshes {
                    if !submesh.indices.is_empty() {
                        let vertices = build_vertices(submesh);
                        let vertex_data = bytemuck::cast_slice::<Vertex, u8>(&vertices);
                        let index_data = bytemuck::cast_slice::<u32, u8>(&submesh.indices);

                        gpu_mesh.vertex_buffer = self.device.new_buffer_with_data(
                            vertex_data.as_ptr() as *const c_void,
                            vertex_data.len() as u64,
                            MTLResourceOptions::StorageModeShared,
                        );
                        gpu_mesh.index_buffer = self.device.new_buffer_with_data(
                            index_data.as_ptr() as *const c_void,
                            index_data.len() as u64,
                            MTLResourceOptions::StorageModeShared,
                        );
                        gpu_mesh.index_count = submesh.indices.len() as u64;
                        break;
                    }
                }
                gpu_mesh.cached_generation = surface.generation;
            }
        }
    }

    fn encode_render_pass(
        &self,
        cmd_buf: &CommandBufferRef,
        state: &[f32],
        is_image_sequence: bool,
    ) {
        let pass_desc = RenderPassDescriptor::new();
        let color_att = pass_desc.color_attachments().object_at(0).unwrap();
        color_att.set_texture(Some(&self.msaa_texture));
        color_att.set_load_action(MTLLoadAction::Clear);
        if is_image_sequence {
            // Resolve MSAA → non-MSAA texture (avoids NV12 chroma subsampling)
            color_att.set_resolve_texture(Some(&self.resolve_texture));
            color_att.set_store_action(MTLStoreAction::MultisampleResolve);
        } else {
            // Store MSAA samples for NV12 compute kernel to read directly
            color_att.set_store_action(MTLStoreAction::Store);
        }
        color_att.set_clear_color(MTLClearColor::new(
            self.background_color[0] as f64,
            self.background_color[1] as f64,
            self.background_color[2] as f64,
            self.background_color[3] as f64,
        ));

        let depth_att = pass_desc.depth_attachment().unwrap();
        depth_att.set_texture(Some(&self.depth_texture));
        depth_att.set_load_action(MTLLoadAction::Clear);
        depth_att.set_store_action(MTLStoreAction::DontCare);
        depth_att.set_clear_depth(1.0);

        let encoder = cmd_buf.new_render_command_encoder(pass_desc);
        encoder.set_render_pipeline_state(&self.pipeline);
        encoder.set_depth_stencil_state(&self.ds_state);

        encoder.set_vertex_bytes(
            1,
            std::mem::size_of::<CameraUniforms>() as u64,
            &self.camera_uniforms as *const CameraUniforms as *const c_void,
        );

        // Classify meshes into opaque and transparent buckets
        let mut opaque_indices: Vec<usize> = Vec::new();
        let mut transparent_indices: Vec<usize> = Vec::new();
        for (i, gpu_mesh) in self.gpu_meshes.iter().enumerate() {
            let base = gpu_mesh.mobject_id as usize * STRIDE;
            if state[base + ACTIVE] == 0.0 || state[base + OPACITY] <= 0.0 {
                continue;
            }
            let opacity = state[base + OPACITY];
            if opacity >= 1.0 {
                opaque_indices.push(i);
            } else {
                transparent_indices.push(i);
            }
        }

        // Sort opaque by z_index ascending
        opaque_indices.sort_by(|&a, &b| {
            let za = state[self.gpu_meshes[a].mobject_id as usize * STRIDE + Z_INDEX];
            let zb = state[self.gpu_meshes[b].mobject_id as usize * STRIDE + Z_INDEX];
            za.partial_cmp(&zb).unwrap_or(std::cmp::Ordering::Equal)
        });
        // Sort transparent by z_index ascending, then position_z descending (back-to-front)
        transparent_indices.sort_by(|&a, &b| {
            let ba = self.gpu_meshes[a].mobject_id as usize * STRIDE;
            let bb = self.gpu_meshes[b].mobject_id as usize * STRIDE;
            let za = state[ba + Z_INDEX];
            let zb = state[bb + Z_INDEX];
            match za.partial_cmp(&zb).unwrap_or(std::cmp::Ordering::Equal) {
                std::cmp::Ordering::Equal => {
                    let pza = state[ba + POSITION_X + 2];
                    let pzb = state[bb + POSITION_X + 2];
                    // Descending position_z (back-to-front)
                    pzb.partial_cmp(&pza).unwrap_or(std::cmp::Ordering::Equal)
                }
                ord => ord,
            }
        });

        // Pass 1: Opaque meshes, Pass 2: Transparent meshes
        for &idx in opaque_indices.iter().chain(transparent_indices.iter()) {
            let gpu_mesh = &self.gpu_meshes[idx];
            let base = gpu_mesh.mobject_id as usize * STRIDE;

            let side = state[base + SIDE] as u32;
            let cull_mode = match side {
                1 => MTLCullMode::Front,
                2 => MTLCullMode::None,
                _ => MTLCullMode::Back,
            };
            encoder.set_cull_mode(cull_mode);

            let uniforms = build_draw_uniforms(state, gpu_mesh.mobject_id);

            encoder.set_vertex_bytes(
                0,
                std::mem::size_of::<DrawUniforms>() as u64,
                &uniforms as *const DrawUniforms as *const c_void,
            );
            encoder.set_fragment_bytes(
                0,
                std::mem::size_of::<DrawUniforms>() as u64,
                &uniforms as *const DrawUniforms as *const c_void,
            );

            encoder.set_vertex_buffer(2, Some(&gpu_mesh.vertex_buffer), 0);

            encoder.draw_indexed_primitives(
                MTLPrimitiveType::Triangle,
                gpu_mesh.index_count,
                MTLIndexType::UInt32,
                &gpu_mesh.index_buffer,
                0,
            );
        }

        // Draw textured meshes
        if !self.gpu_textured_meshes.is_empty() {
            encoder.set_render_pipeline_state(&self.textured_pipeline);
            encoder.set_depth_stencil_state(&self.ds_state);

            encoder.set_vertex_bytes(
                1,
                std::mem::size_of::<CameraUniforms>() as u64,
                &self.camera_uniforms as *const CameraUniforms as *const c_void,
            );

            for gpu_mesh in &self.gpu_textured_meshes {
                // Skip inactive or fully transparent meshes
                let base = gpu_mesh.mobject_id as usize * STRIDE;
                if state[base + ACTIVE] == 0.0 || state[base + OPACITY] <= 0.0 {
                    continue;
                }

                let uniforms = build_draw_uniforms(state, gpu_mesh.mobject_id);

                encoder.set_vertex_bytes(
                    0,
                    std::mem::size_of::<DrawUniforms>() as u64,
                    &uniforms as *const DrawUniforms as *const c_void,
                );
                encoder.set_fragment_bytes(
                    0,
                    std::mem::size_of::<DrawUniforms>() as u64,
                    &uniforms as *const DrawUniforms as *const c_void,
                );

                // Select frame
                let base = gpu_mesh.mobject_id as usize * STRIDE;
                let frame_idx = if gpu_mesh.frame_count > 1 && base + FRAME_INDEX < state.len() {
                    (state[base + FRAME_INDEX] as usize) % gpu_mesh.frame_count as usize
                } else {
                    0
                };

                encoder.set_vertex_buffer(2, Some(&gpu_mesh.vertex_buffer), 0);
                encoder.set_fragment_texture(0, Some(&gpu_mesh.textures[frame_idx]));
                encoder.set_fragment_sampler_state(0, Some(&gpu_mesh.sampler_state));

                encoder.draw_indexed_primitives(
                    MTLPrimitiveType::Triangle,
                    gpu_mesh.index_count,
                    MTLIndexType::UInt32,
                    &gpu_mesh.index_buffer,
                    0,
                );
            }
        }

        encoder.end_encoding();
    }

    fn encode_nv12_pass(&self, cmd_buf: &CommandBufferRef, slot: usize) {
        let compute_encoder = cmd_buf.new_compute_command_encoder();
        compute_encoder.set_compute_pipeline_state(&self.nv12_pipeline);
        compute_encoder.set_texture(0, Some(&self.msaa_texture));
        compute_encoder.set_buffer(0, Some(&self.nv12_buffers[slot]), 0);

        let threads_per_group = MTLSize {
            width: 16,
            height: 16,
            depth: 1,
        };
        let num_groups = MTLSize {
            width: (self.width as u64 / 4).div_ceil(16),
            height: (self.height as u64 / 2).div_ceil(16),
            depth: 1,
        };
        compute_encoder.dispatch_thread_groups(num_groups, threads_per_group);
        compute_encoder.end_encoding();
    }

    fn nv12_readback(&self, slot: usize, out: &mut [u8]) {
        let ptr = self.nv12_buffers[slot].contents() as *const u8;
        unsafe {
            std::ptr::copy_nonoverlapping(ptr, out.as_mut_ptr(), out.len());
        }
    }

    fn encode_rgba_blit(&self, cmd_buf: &CommandBufferRef, slot: usize) {
        let blit = cmd_buf.new_blit_command_encoder();
        let bytes_per_row = self.width as u64 * 4;
        blit.copy_from_texture_to_buffer(
            &self.resolve_texture,
            0,
            0,
            MTLOrigin { x: 0, y: 0, z: 0 },
            MTLSize {
                width: self.width as u64,
                height: self.height as u64,
                depth: 1,
            },
            &self.rgba_buffers[slot],
            0,
            bytes_per_row,
            bytes_per_row * self.height as u64,
            MTLBlitOption::empty(),
        );
        blit.end_encoding();
    }

    fn rgba_readback(&self, slot: usize, out: &mut [u8]) {
        let ptr = self.rgba_buffers[slot].contents() as *const u8;
        unsafe {
            std::ptr::copy_nonoverlapping(ptr, out.as_mut_ptr(), out.len());
        }
    }

    /// Force Metal to compile shaders, avoiding lazy compilation stutter on frame 0.
    fn warmup(&mut self) {
        if self.warmup_done {
            return;
        }

        let cmd = self.queue.new_command_buffer();

        let pass = RenderPassDescriptor::new();
        let att = pass.color_attachments().object_at(0).unwrap();
        att.set_texture(Some(&self.msaa_texture));
        att.set_load_action(MTLLoadAction::Clear);
        att.set_store_action(MTLStoreAction::Store);
        att.set_clear_color(MTLClearColor::new(0.0, 0.0, 0.0, 1.0));

        let depth_att = pass.depth_attachment().unwrap();
        depth_att.set_texture(Some(&self.depth_texture));
        depth_att.set_load_action(MTLLoadAction::Clear);
        depth_att.set_store_action(MTLStoreAction::DontCare);
        depth_att.set_clear_depth(1.0);

        let enc = cmd.new_render_command_encoder(pass);
        enc.set_render_pipeline_state(&self.pipeline);
        enc.set_depth_stencil_state(&self.ds_state);
        // Also warm up textured pipeline
        enc.set_render_pipeline_state(&self.textured_pipeline);
        enc.end_encoding();

        let compute = cmd.new_compute_command_encoder();
        compute.set_compute_pipeline_state(&self.nv12_pipeline);
        compute.set_texture(0, Some(&self.msaa_texture));
        compute.set_buffer(0, Some(&self.nv12_buffers[0]), 0);
        compute.dispatch_thread_groups(
            MTLSize {
                width: 1,
                height: 1,
                depth: 1,
            },
            MTLSize {
                width: 16,
                height: 16,
                depth: 1,
            },
        );
        compute.end_encoding();

        cmd.commit();
        cmd.wait_until_completed();
        self.warmup_done = true;
    }

    fn render_loop(
        &mut self,
        py: Python<'_>,
        evaluate_frame: &Py<PyAny>,
        surface_refs: &[Py<crate::tessellation::Surface>],
        object3d_refs: &[Py<crate::scene_node::Object3D>],
        camera_ref: &Py<crate::camera::Camera>,
        cfg: &RenderConfig,
    ) -> Result<(), String> {
        let total_frames = ((cfg.total_duration * cfg.fps as f32) as u32).max(1);
        let fps = cfg.fps;
        let output_path = cfg.output_path.to_str().unwrap();
        let output_width = cfg.output_width;
        let output_height = cfg.output_height;
        let is_image_sequence = output_path.ends_with(".png") || output_path.ends_with(".jpg");

        let frame_size = if is_image_sequence {
            self.rgba_frame_size as usize
        } else {
            self.nv12_frame_size as usize
        };
        let fps_f32 = fps as f32;

        // Spawn ffmpeg concurrently with Metal warmup
        let (w, h, fps_u32, fsz) = (self.width, self.height, fps, frame_size);
        let (ow, oh) = (output_width, output_height);
        let path = output_path.to_string();
        let ffmpeg_handle =
            std::thread::spawn(move || FfmpegPipeline::spawn(w, h, fps_u32, &path, fsz, ow, oh));

        self.warmup();

        let pipeline = ffmpeg_handle
            .join()
            .map_err(|_| "ffmpeg spawn thread panicked".to_string())??;

        let mut pending: VecDeque<(usize, CommandBuffer)> = VecDeque::new();
        let mut state: Vec<f32> = Vec::new();

        for frame_idx in 0..total_frames {
            let t = frame_idx as f32 / fps_f32;
            let slot = frame_idx as usize % PIPELINE_DEPTH;

            if pending.len() == PIPELINE_DEPTH {
                let (old_slot, old_cmd) = pending.pop_front().unwrap();
                old_cmd.wait_until_completed();

                let mut pixels = pipeline
                    .buf_pool_rx
                    .recv()
                    .map_err(|_| "Buffer pool closed".to_string())?;
                if is_image_sequence {
                    self.rgba_readback(old_slot, &mut pixels);
                } else {
                    self.nv12_readback(old_slot, &mut pixels);
                }
                pipeline
                    .frame_tx
                    .send(pixels)
                    .map_err(|e| format!("Channel send error: {e}"))?;
            }

            // Evaluate scene state for this frame, then snapshot to state buffer.
            evaluate_frame
                .call1(py, (t,))
                .map_err(|e| format!("evaluate_frame error: {e}"))?;
            crate::render_context::snapshot_surfaces(py, surface_refs, object3d_refs, &mut state);
            self.sync_dirty_surfaces(py, surface_refs);

            // Read camera state per-frame
            {
                let cam = camera_ref.borrow(py);
                self.camera_uniforms = CameraUniforms {
                    view_projection: build_view_projection(
                        self.width,
                        self.height,
                        cam.frame_height,
                        cam.position,
                        cam.quaternion,
                        cam.projection,
                        cam.fov,
                    ),
                };
                self.background_color = [
                    cam.background.0 as f32 / 255.0,
                    cam.background.1 as f32 / 255.0,
                    cam.background.2 as f32 / 255.0,
                    1.0,
                ];
            }

            let cmd_buf = self.queue.new_command_buffer();
            self.encode_render_pass(cmd_buf, &state, is_image_sequence);
            if is_image_sequence {
                self.encode_rgba_blit(cmd_buf, slot);
            } else {
                self.encode_nv12_pass(cmd_buf, slot);
            }

            let owned = cmd_buf.to_owned();
            cmd_buf.commit();
            pending.push_back((slot, owned));
        }

        while let Some((old_slot, old_cmd)) = pending.pop_front() {
            old_cmd.wait_until_completed();

            let mut pixels = pipeline
                .buf_pool_rx
                .recv()
                .map_err(|_| "Buffer pool closed".to_string())?;
            if is_image_sequence {
                self.rgba_readback(old_slot, &mut pixels);
            } else {
                self.nv12_readback(old_slot, &mut pixels);
            }
            pipeline
                .frame_tx
                .send(pixels)
                .map_err(|e| format!("Channel send error: {e}"))?;
        }

        pipeline.finish()
    }
}
