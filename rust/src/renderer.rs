use pyo3::prelude::*;
use wgpu::util::DeviceExt;

use crate::common::*;
use crate::render_context::{ACTIVE, FRAME_INDEX, OPACITY, POSITION_X, SIDE, STRIDE, Z_INDEX};
use crate::tessellation::{Mesh, Texture};

#[allow(dead_code)]
struct GpuMesh {
    vertex_buffer: wgpu::Buffer,
    index_buffer: wgpu::Buffer,
    draw_uniform_buffer: wgpu::Buffer,
    draw_bind_group: wgpu::BindGroup,
    index_count: u32,
    mobject_id: u32,
}

#[allow(dead_code)]
struct GpuTexturedMesh {
    vertex_buffer: wgpu::Buffer,
    index_buffer: wgpu::Buffer,
    draw_uniform_buffer: wgpu::Buffer,
    draw_bind_group: wgpu::BindGroup,
    texture_bind_groups: Vec<wgpu::BindGroup>,
    index_count: u32,
    mobject_id: u32,
    frame_count: u32,
}

#[pyclass]
#[allow(dead_code)]
pub struct GpuRenderer {
    device: wgpu::Device,
    queue: wgpu::Queue,
    pipeline_cull_back: wgpu::RenderPipeline,
    pipeline_cull_front: wgpu::RenderPipeline,
    pipeline_cull_none: wgpu::RenderPipeline,
    msaa_texture: wgpu::Texture,
    depth_texture: wgpu::Texture,
    // NV12 compute conversion
    nv12_compute_pipeline: wgpu::ComputePipeline,
    nv12_bind_groups: [wgpu::BindGroup; PIPELINE_DEPTH],
    nv12_storage_buffers: [wgpu::Buffer; PIPELINE_DEPTH],
    nv12_staging_buffers: [wgpu::Buffer; PIPELINE_DEPTH],
    nv12_frame_size: u64,
    // Shared state
    camera_buffer: wgpu::Buffer,
    camera_bind_group: wgpu::BindGroup,
    draw_bind_group_layout: wgpu::BindGroupLayout,
    // Textured pipeline
    textured_pipeline: wgpu::RenderPipeline,
    texture_bind_group_layout: wgpu::BindGroupLayout,
    gpu_textured_meshes: Vec<GpuTexturedMesh>,
    width: u32,
    height: u32,
    gpu_meshes: Vec<GpuMesh>,
    num_mobjects: u32,
    background_color: [f32; 4],
}

#[pymethods]
impl GpuRenderer {
    #[new]
    pub fn new(width: u32, height: u32) -> PyResult<Self> {
        let background_color = [0.0f32, 0.0, 0.0, 1.0];
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            compatible_surface: None,
            force_fallback_adapter: false,
        }))
        .map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("No GPU adapter found: {e}"))
        })?;

        let (device, queue) =
            pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor::default()))
                .map_err(|e| {
                    pyo3::exceptions::PyRuntimeError::new_err(format!(
                        "Failed to create device: {e}"
                    ))
                })?;

        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: None,
            source: wgpu::ShaderSource::Wgsl(include_str!("shaders/main.wgsl").into()),
        });

        let draw_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: None,
                entries: &[wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX | wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                }],
            });

        let camera_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: None,
                entries: &[wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                }],
            });

        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&draw_bind_group_layout, &camera_bind_group_layout],
            immediate_size: 0,
        });

        let vertex_buffer_layouts = [
            // Primary vertex buffer (slot 0)
            wgpu::VertexBufferLayout {
                array_stride: std::mem::size_of::<Vertex>() as u64,
                step_mode: wgpu::VertexStepMode::Vertex,
                attributes: &[
                    wgpu::VertexAttribute {
                        format: wgpu::VertexFormat::Float32x3,
                        offset: 0,
                        shader_location: 0,
                    },
                    wgpu::VertexAttribute {
                        format: wgpu::VertexFormat::Float32x3,
                        offset: 12,
                        shader_location: 1,
                    },
                    wgpu::VertexAttribute {
                        format: wgpu::VertexFormat::Float32x2,
                        offset: 24,
                        shader_location: 2,
                    },
                    wgpu::VertexAttribute {
                        format: wgpu::VertexFormat::Float32x4,
                        offset: 32,
                        shader_location: 3,
                    },
                ],
            },
        ];

        let depth_format = wgpu::TextureFormat::Depth32Float;

        let create_pipeline = |cull_mode: Option<wgpu::Face>| {
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: None,
                layout: Some(&pipeline_layout),
                vertex: wgpu::VertexState {
                    module: &shader,
                    entry_point: Some("vs_main"),
                    buffers: &vertex_buffer_layouts,
                    compilation_options: Default::default(),
                },
                fragment: Some(wgpu::FragmentState {
                    module: &shader,
                    entry_point: Some("fs_main"),
                    targets: &[Some(wgpu::ColorTargetState {
                        format: wgpu::TextureFormat::Rgba8Unorm,
                        blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                        write_mask: wgpu::ColorWrites::ALL,
                    })],
                    compilation_options: Default::default(),
                }),
                primitive: wgpu::PrimitiveState {
                    topology: wgpu::PrimitiveTopology::TriangleList,
                    front_face: wgpu::FrontFace::Ccw,
                    cull_mode,
                    ..Default::default()
                },
                depth_stencil: Some(wgpu::DepthStencilState {
                    format: depth_format,
                    depth_write_enabled: true,
                    depth_compare: wgpu::CompareFunction::LessEqual,
                    stencil: wgpu::StencilState::default(),
                    bias: wgpu::DepthBiasState::default(),
                }),
                multisample: wgpu::MultisampleState {
                    count: MSAA_SAMPLES,
                    mask: !0,
                    alpha_to_coverage_enabled: false,
                },
                multiview_mask: None,
                cache: None,
            })
        };

        let pipeline_cull_back = create_pipeline(Some(wgpu::Face::Back));
        let pipeline_cull_front = create_pipeline(Some(wgpu::Face::Front));
        let pipeline_cull_none = create_pipeline(None);

        // Textured pipeline
        let textured_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: None,
            source: wgpu::ShaderSource::Wgsl(include_str!("shaders/textured.wgsl").into()),
        });

        let texture_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: None,
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Texture {
                            sample_type: wgpu::TextureSampleType::Float { filterable: true },
                            view_dimension: wgpu::TextureViewDimension::D2,
                            multisampled: false,
                        },
                        count: None,
                    },
                    wgpu::BindGroupLayoutEntry {
                        binding: 1,
                        visibility: wgpu::ShaderStages::FRAGMENT,
                        ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                        count: None,
                    },
                ],
            });

        let textured_pipeline_layout =
            device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: None,
                bind_group_layouts: &[
                    &draw_bind_group_layout,
                    &camera_bind_group_layout,
                    &texture_bind_group_layout,
                ],
                immediate_size: 0,
            });

        let textured_pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: None,
            layout: Some(&textured_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &textured_shader,
                entry_point: Some("vs_main"),
                buffers: &[wgpu::VertexBufferLayout {
                    array_stride: std::mem::size_of::<TexturedVertex>() as u64,
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &[
                        wgpu::VertexAttribute {
                            format: wgpu::VertexFormat::Float32x3,
                            offset: 0,
                            shader_location: 0,
                        },
                        wgpu::VertexAttribute {
                            format: wgpu::VertexFormat::Float32x2,
                            offset: 12,
                            shader_location: 1,
                        },
                    ],
                }],
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: &textured_shader,
                entry_point: Some("fs_main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                front_face: wgpu::FrontFace::Ccw,
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: depth_format,
                depth_write_enabled: true,
                depth_compare: wgpu::CompareFunction::LessEqual,
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState {
                count: MSAA_SAMPLES,
                mask: !0,
                alpha_to_coverage_enabled: false,
            },
            multiview_mask: None,
            cache: None,
        });

        // MSAA texture — TEXTURE_BINDING lets the NV12 compute shader read samples directly
        let msaa_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: None,
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: MSAA_SAMPLES,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            view_formats: &[],
        });

        // Depth texture (MSAA)
        let depth_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: None,
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: MSAA_SAMPLES,
            dimension: wgpu::TextureDimension::D2,
            format: depth_format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        });

        // NV12 compute pipeline
        let nv12_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: None,
            source: wgpu::ShaderSource::Wgsl(include_str!("shaders/nv12_convert.wgsl").into()),
        });

        let nv12_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: None,
                entries: &[
                    wgpu::BindGroupLayoutEntry {
                        binding: 0,
                        visibility: wgpu::ShaderStages::COMPUTE,
                        ty: wgpu::BindingType::Texture {
                            sample_type: wgpu::TextureSampleType::Float { filterable: false },
                            view_dimension: wgpu::TextureViewDimension::D2,
                            multisampled: true,
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

        let nv12_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&nv12_bind_group_layout],
            immediate_size: 0,
        });

        let nv12_compute_pipeline =
            device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: None,
                layout: Some(&nv12_pipeline_layout),
                module: &nv12_shader,
                entry_point: Some("nv12_convert"),
                compilation_options: Default::default(),
                cache: None,
            });

        let nv12_frame_size = (width as u64 * height as u64 * 3) / 2;

        let nv12_storage_buffers = std::array::from_fn(|_| {
            device.create_buffer(&wgpu::BufferDescriptor {
                label: None,
                size: nv12_frame_size,
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            })
        });

        let nv12_staging_buffers = std::array::from_fn(|_| {
            device.create_buffer(&wgpu::BufferDescriptor {
                label: None,
                size: nv12_frame_size,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            })
        });

        let msaa_view = msaa_texture.create_view(&Default::default());

        let nv12_bind_groups = std::array::from_fn(|i| {
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: None,
                layout: &nv12_bind_group_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::TextureView(&msaa_view),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: nv12_storage_buffers[i].as_entire_binding(),
                    },
                ],
            })
        });

        let camera_uniforms = CameraUniforms {
            view_projection: orthographic_projection(width, height, 8.0),
        };
        let camera_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: None,
            contents: bytemuck::bytes_of(&camera_uniforms),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        let camera_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &camera_bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: camera_buffer.as_entire_binding(),
            }],
        });

        Ok(GpuRenderer {
            device,
            queue,
            pipeline_cull_back,
            pipeline_cull_front,
            pipeline_cull_none,
            msaa_texture,
            depth_texture,
            nv12_compute_pipeline,
            nv12_bind_groups,
            nv12_storage_buffers,
            nv12_staging_buffers,
            nv12_frame_size,
            camera_buffer,
            camera_bind_group,
            draw_bind_group_layout,
            textured_pipeline,
            texture_bind_group_layout,
            gpu_textured_meshes: Vec::new(),
            width,
            height,
            gpu_meshes: Vec::new(),
            num_mobjects: 0,
            background_color,
        })
    }
}

#[cfg_attr(target_os = "macos", allow(dead_code))]
impl GpuRenderer {
    pub(crate) fn upload_meshes(
        &mut self,
        meshes: Vec<Mesh>,
        textures: &[Option<Texture>],
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
                let vertex_buffer =
                    self.device
                        .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                            label: None,
                            contents: bytemuck::cast_slice(&vertices),
                            usage: wgpu::BufferUsages::VERTEX,
                        });

                let index_buffer =
                    self.device
                        .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                            label: None,
                            contents: bytemuck::cast_slice(&geo.texture_indices),
                            usage: wgpu::BufferUsages::INDEX,
                        });

                let draw_uniform_buffer =
                    self.device
                        .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                            label: None,
                            contents: bytemuck::bytes_of(&DrawUniforms {
                                clip_threshold: 1.0,
                                opacity: 1.0,
                                shading: 0.0,
                                _pad0: 0.0,
                                position: [0.0, 0.0, 0.0, 0.0],
                                scale: [1.0, 1.0, 1.0, 0.0],
                                rotation: [0.0, 0.0, 0.0, 1.0],
                                tint: [0.0, 0.0, 0.0, 0.0],
                            }),
                            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                        });

                let draw_bind_group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: None,
                    layout: &self.draw_bind_group_layout,
                    entries: &[wgpu::BindGroupEntry {
                        binding: 0,
                        resource: draw_uniform_buffer.as_entire_binding(),
                    }],
                });

                // Create sampler (shared across frames)
                let sampler = self.device.create_sampler(&wgpu::SamplerDescriptor {
                    mag_filter: wgpu::FilterMode::Linear,
                    min_filter: wgpu::FilterMode::Linear,
                    address_mode_u: wgpu::AddressMode::ClampToEdge,
                    address_mode_v: wgpu::AddressMode::ClampToEdge,
                    ..Default::default()
                });

                // Create a GPU texture + bind group per frame
                let mut texture_bind_groups = Vec::with_capacity(tex.frames.len());
                let tex_size = wgpu::Extent3d {
                    width: tex.width,
                    height: tex.height,
                    depth_or_array_layers: 1,
                };

                for frame_data in &tex.frames {
                    let gpu_texture = self.device.create_texture(&wgpu::TextureDescriptor {
                        label: None,
                        size: tex_size,
                        mip_level_count: 1,
                        sample_count: 1,
                        dimension: wgpu::TextureDimension::D2,
                        format: wgpu::TextureFormat::Rgba8Unorm,
                        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
                        view_formats: &[],
                    });

                    self.queue.write_texture(
                        wgpu::TexelCopyTextureInfo {
                            texture: &gpu_texture,
                            mip_level: 0,
                            origin: wgpu::Origin3d::ZERO,
                            aspect: wgpu::TextureAspect::All,
                        },
                        frame_data,
                        wgpu::TexelCopyBufferLayout {
                            offset: 0,
                            bytes_per_row: Some(tex.width * 4),
                            rows_per_image: None,
                        },
                        tex_size,
                    );

                    let tex_view = gpu_texture.create_view(&Default::default());
                    let bind_group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                        label: None,
                        layout: &self.texture_bind_group_layout,
                        entries: &[
                            wgpu::BindGroupEntry {
                                binding: 0,
                                resource: wgpu::BindingResource::TextureView(&tex_view),
                            },
                            wgpu::BindGroupEntry {
                                binding: 1,
                                resource: wgpu::BindingResource::Sampler(&sampler),
                            },
                        ],
                    });
                    texture_bind_groups.push(bind_group);
                }

                self.gpu_textured_meshes.push(GpuTexturedMesh {
                    vertex_buffer,
                    index_buffer,
                    draw_uniform_buffer,
                    draw_bind_group,
                    texture_bind_groups,
                    index_count: geo.texture_indices.len() as u32,
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
                let vertex_buffer =
                    self.device
                        .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                            label: None,
                            contents: bytemuck::cast_slice(&vertices),
                            usage: wgpu::BufferUsages::VERTEX,
                        });

                let index_buffer =
                    self.device
                        .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                            label: None,
                            contents: bytemuck::cast_slice(&submesh.indices),
                            usage: wgpu::BufferUsages::INDEX,
                        });

                let draw_uniform_buffer =
                    self.device
                        .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                            label: None,
                            contents: bytemuck::bytes_of(&DrawUniforms {
                                clip_threshold: 1.0,
                                opacity: 1.0,
                                shading: 0.0,
                                _pad0: 0.0,
                                position: [0.0, 0.0, 0.0, 0.0],
                                scale: [1.0, 1.0, 1.0, 0.0],
                                rotation: [0.0, 0.0, 0.0, 1.0],
                                tint: [0.0, 0.0, 0.0, 0.0],
                            }),
                            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                        });

                let draw_bind_group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: None,
                    layout: &self.draw_bind_group_layout,
                    entries: &[wgpu::BindGroupEntry {
                        binding: 0,
                        resource: draw_uniform_buffer.as_entire_binding(),
                    }],
                });

                self.gpu_meshes.push(GpuMesh {
                    vertex_buffer,
                    index_buffer,
                    draw_uniform_buffer,
                    draw_bind_group,
                    index_count: submesh.indices.len() as u32,
                    mobject_id,
                });
            }
        }
    }
}

#[cfg_attr(target_os = "macos", allow(dead_code))]
impl GpuRenderer {
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

    fn update_camera_state(&mut self, py: Python<'_>, camera_ref: &Py<crate::camera::Camera>) {
        let cam = camera_ref.borrow(py);
        let camera_uniforms = CameraUniforms {
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
        self.queue
            .write_buffer(&self.camera_buffer, 0, bytemuck::bytes_of(&camera_uniforms));
        self.background_color = [
            cam.background.0 as f32 / 255.0,
            cam.background.1 as f32 / 255.0,
            cam.background.2 as f32 / 255.0,
            1.0,
        ];
    }

    fn encode_render_pass(&self, encoder: &mut wgpu::CommandEncoder, state: &[f32]) {
        let msaa_view = self.msaa_texture.create_view(&Default::default());
        let depth_view = self.depth_texture.create_view(&Default::default());

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

        // Write uniforms for all active meshes (before beginning render pass)
        for &idx in opaque_indices.iter().chain(transparent_indices.iter()) {
            let gpu_mesh = &self.gpu_meshes[idx];
            let uniforms = build_draw_uniforms(state, gpu_mesh.mobject_id);
            self.queue.write_buffer(
                &gpu_mesh.draw_uniform_buffer,
                0,
                bytemuck::bytes_of(&uniforms),
            );
        }

        {
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: None,
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &msaa_view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color {
                            r: self.background_color[0] as f64,
                            g: self.background_color[1] as f64,
                            b: self.background_color[2] as f64,
                            a: self.background_color[3] as f64,
                        }),
                        store: wgpu::StoreOp::Store,
                    },
                    depth_slice: None,
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                ..Default::default()
            });

            rpass.set_bind_group(1, &self.camera_bind_group, &[]);

            // Pass 1: Opaque meshes, Pass 2: Transparent meshes
            for &idx in opaque_indices.iter().chain(transparent_indices.iter()) {
                let gpu_mesh = &self.gpu_meshes[idx];
                let base = gpu_mesh.mobject_id as usize * STRIDE;

                let side = state[base + SIDE] as u32;
                let pipeline = match side {
                    1 => &self.pipeline_cull_front,
                    2 => &self.pipeline_cull_none,
                    _ => &self.pipeline_cull_back,
                };
                rpass.set_pipeline(pipeline);

                rpass.set_bind_group(0, &gpu_mesh.draw_bind_group, &[]);
                rpass.set_bind_group(1, &self.camera_bind_group, &[]);
                rpass.set_vertex_buffer(0, gpu_mesh.vertex_buffer.slice(..));
                rpass.set_index_buffer(gpu_mesh.index_buffer.slice(..), wgpu::IndexFormat::Uint32);
                rpass.draw_indexed(0..gpu_mesh.index_count, 0, 0..1);
            }

            // Draw textured meshes
            if !self.gpu_textured_meshes.is_empty() {
                rpass.set_pipeline(&self.textured_pipeline);
                rpass.set_bind_group(1, &self.camera_bind_group, &[]);

                for gpu_mesh in &self.gpu_textured_meshes {
                    // Skip inactive or fully transparent meshes
                    let base = gpu_mesh.mobject_id as usize * STRIDE;
                    if state[base + ACTIVE] == 0.0 || state[base + OPACITY] <= 0.0 {
                        continue;
                    }

                    let uniforms = build_draw_uniforms(state, gpu_mesh.mobject_id);

                    self.queue.write_buffer(
                        &gpu_mesh.draw_uniform_buffer,
                        0,
                        bytemuck::bytes_of(&uniforms),
                    );

                    // Select frame
                    let base = gpu_mesh.mobject_id as usize * STRIDE;
                    let frame_idx = if gpu_mesh.frame_count > 1 && base + FRAME_INDEX < state.len()
                    {
                        (state[base + FRAME_INDEX] as usize) % gpu_mesh.frame_count as usize
                    } else {
                        0
                    };

                    rpass.set_bind_group(0, &gpu_mesh.draw_bind_group, &[]);
                    rpass.set_bind_group(2, &gpu_mesh.texture_bind_groups[frame_idx], &[]);
                    rpass.set_vertex_buffer(0, gpu_mesh.vertex_buffer.slice(..));
                    rpass.set_index_buffer(
                        gpu_mesh.index_buffer.slice(..),
                        wgpu::IndexFormat::Uint32,
                    );
                    rpass.draw_indexed(0..gpu_mesh.index_count, 0, 0..1);
                }
            }
        }
    }

    /// Render + NV12 compute + copy to staging. Returns SubmissionIndex for waiting.
    fn submit_frame(&self, state: &[f32], slot: usize) -> wgpu::SubmissionIndex {
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });

        self.encode_render_pass(&mut encoder, state);

        {
            let mut cpass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: None,
                ..Default::default()
            });
            cpass.set_pipeline(&self.nv12_compute_pipeline);
            cpass.set_bind_group(0, &self.nv12_bind_groups[slot], &[]);

            let dispatch_x = (self.width / 4).div_ceil(8);
            let dispatch_y = (self.height / 2).div_ceil(8);
            cpass.dispatch_workgroups(dispatch_x, dispatch_y, 1);
        }

        encoder.copy_buffer_to_buffer(
            &self.nv12_storage_buffers[slot],
            0,
            &self.nv12_staging_buffers[slot],
            0,
            self.nv12_frame_size,
        );

        self.queue.submit(Some(encoder.finish()))
    }

    fn nv12_readback(&self, slot: usize, out: &mut [u8]) {
        let data = self.nv12_staging_buffers[slot].slice(..).get_mapped_range();
        out.copy_from_slice(&data[..out.len()]);
        drop(data);
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

        let nv12_size = self.nv12_frame_size as usize;
        let fps_f32 = fps as f32;

        let pipeline = FfmpegPipeline::spawn(
            self.width,
            self.height,
            fps,
            output_path,
            nv12_size,
            output_width,
            output_height,
        )?;

        let initial = total_frames.min(PIPELINE_DEPTH as u32 - 1);
        let mut pending: std::collections::VecDeque<(usize, wgpu::SubmissionIndex)> =
            std::collections::VecDeque::new();
        let mut state: Vec<f32> = Vec::new();

        // Pre-fill pipeline slots
        for i in 0..initial {
            let t = i as f32 / fps_f32;
            let slot = i as usize % PIPELINE_DEPTH;
            evaluate_frame
                .call1(py, (t,))
                .map_err(|e| format!("evaluate_frame error: {e}"))?;
            crate::render_context::snapshot_surfaces(py, surface_refs, object3d_refs, &mut state);
            self.update_camera_state(py, camera_ref);
            let idx = self.submit_frame(&state, slot);
            pending.push_back((slot, idx));
        }

        if let Some((oldest_slot, oldest_idx)) = pending.front() {
            self.device
                .poll(wgpu::PollType::Wait {
                    submission_index: Some(oldest_idx.clone()),
                    timeout: None,
                })
                .unwrap();
            self.nv12_staging_buffers[*oldest_slot]
                .slice(..)
                .map_async(wgpu::MapMode::Read, |_| {});
        }

        // Submit new frame, then wait for oldest, readback, map next-oldest
        for frame_idx in initial..total_frames {
            let t = frame_idx as f32 / fps_f32;
            let slot = frame_idx as usize % PIPELINE_DEPTH;

            evaluate_frame
                .call1(py, (t,))
                .map_err(|e| format!("evaluate_frame error: {e}"))?;
            crate::render_context::snapshot_surfaces(py, surface_refs, object3d_refs, &mut state);
            self.update_camera_state(py, camera_ref);
            let new_idx = self.submit_frame(&state, slot);

            let (old_slot, old_idx) = pending.pop_front().unwrap();
            self.device
                .poll(wgpu::PollType::Wait {
                    submission_index: Some(old_idx),
                    timeout: None,
                })
                .unwrap();

            let mut pixels = pipeline
                .buf_pool_rx
                .recv()
                .map_err(|_| "Buffer pool closed".to_string())?;
            self.nv12_readback(old_slot, &mut pixels);
            self.nv12_staging_buffers[old_slot].unmap();
            pipeline
                .frame_tx
                .send(pixels)
                .map_err(|e| format!("Channel send error: {e}"))?;

            pending.push_back((slot, new_idx));

            if let Some((next_oldest_slot, _)) = pending.front() {
                self.nv12_staging_buffers[*next_oldest_slot]
                    .slice(..)
                    .map_async(wgpu::MapMode::Read, |_| {});
            }
        }

        // Drain remaining
        while let Some((old_slot, old_idx)) = pending.pop_front() {
            self.device
                .poll(wgpu::PollType::Wait {
                    submission_index: Some(old_idx),
                    timeout: None,
                })
                .unwrap();

            let mut pixels = pipeline
                .buf_pool_rx
                .recv()
                .map_err(|_| "Buffer pool closed".to_string())?;
            self.nv12_readback(old_slot, &mut pixels);
            self.nv12_staging_buffers[old_slot].unmap();
            pipeline
                .frame_tx
                .send(pixels)
                .map_err(|e| format!("Channel send error: {e}"))?;

            if let Some((next_slot, _)) = pending.front() {
                self.nv12_staging_buffers[*next_slot]
                    .slice(..)
                    .map_async(wgpu::MapMode::Read, |_| {});
            }
        }

        pipeline.finish()
    }
}
