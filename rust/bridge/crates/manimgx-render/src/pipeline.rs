use manimgx_core::vertex::Vertex;
use wgpu;

pub struct RenderPipelines {
    pub default: wgpu::RenderPipeline,
    pub flat_no_cull: wgpu::RenderPipeline,
    pub textured: wgpu::RenderPipeline,
    pub camera_bind_group_layout: wgpu::BindGroupLayout,
    pub model_bind_group_layout: wgpu::BindGroupLayout,
    pub texture_bind_group_layout: wgpu::BindGroupLayout,
}

impl RenderPipelines {
    pub fn new(
        device: &wgpu::Device,
        color_format: wgpu::TextureFormat,
        sample_count: u32,
    ) -> Self {
        let camera_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("camera_bind_group_layout"),
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

        let model_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("model_bind_group_layout"),
                entries: &[wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: true,
                        min_binding_size: None,
                    },
                    count: None,
                }],
            });

        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("render_pipeline_layout"),
            bind_group_layouts: &[&camera_bind_group_layout, &model_bind_group_layout],
            push_constant_ranges: &[],
        });

        let vertex_buffer_layout = wgpu::VertexBufferLayout {
            array_stride: std::mem::size_of::<Vertex>() as wgpu::BufferAddress,
            step_mode: wgpu::VertexStepMode::Vertex,
            attributes: &[
                // position
                wgpu::VertexAttribute {
                    offset: 0,
                    shader_location: 0,
                    format: wgpu::VertexFormat::Float32x3,
                },
                // normal
                wgpu::VertexAttribute {
                    offset: 12,
                    shader_location: 1,
                    format: wgpu::VertexFormat::Float32x3,
                },
                // color
                wgpu::VertexAttribute {
                    offset: 24,
                    shader_location: 2,
                    format: wgpu::VertexFormat::Float32x4,
                },
            ],
        };

        let default_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("default_shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../../../shaders/default.wgsl").into()),
        });

        let flat_color_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("flat_color_shader"),
            source: wgpu::ShaderSource::Wgsl(
                include_str!("../../../shaders/flat_color.wgsl").into(),
            ),
        });

        let default = Self::create_pipeline(
            device,
            &pipeline_layout,
            &default_shader,
            &vertex_buffer_layout,
            color_format,
            wgpu::PrimitiveTopology::TriangleList,
            None,
            sample_count,
        );

        let flat_no_cull = Self::create_pipeline(
            device,
            &pipeline_layout,
            &flat_color_shader,
            &vertex_buffer_layout,
            color_format,
            wgpu::PrimitiveTopology::TriangleList,
            None,
            sample_count,
        );

        // --- Textured pipeline (for text rendering) ---

        let texture_bind_group_layout =
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some("texture_bind_group_layout"),
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
                label: Some("textured_pipeline_layout"),
                bind_group_layouts: &[
                    &camera_bind_group_layout,
                    &model_bind_group_layout,
                    &texture_bind_group_layout,
                ],
                push_constant_ranges: &[],
            });

        let text_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("text_shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../../../shaders/text.wgsl").into()),
        });

        // Textured pipeline uses the same Vertex layout (UV packed into normal.xy)
        let textured = Self::create_pipeline(
            device,
            &textured_pipeline_layout,
            &text_shader,
            &vertex_buffer_layout,
            color_format,
            wgpu::PrimitiveTopology::TriangleList,
            None, // no culling for 2D text quads at z=0
            sample_count,
        );

        Self {
            default,
            flat_no_cull,
            textured,
            camera_bind_group_layout,
            model_bind_group_layout,
            texture_bind_group_layout,
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn create_pipeline(
        device: &wgpu::Device,
        layout: &wgpu::PipelineLayout,
        shader: &wgpu::ShaderModule,
        vertex_buffer_layout: &wgpu::VertexBufferLayout,
        color_format: wgpu::TextureFormat,
        topology: wgpu::PrimitiveTopology,
        cull_mode: Option<wgpu::Face>,
        sample_count: u32,
    ) -> wgpu::RenderPipeline {
        device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("render_pipeline"),
            layout: Some(layout),
            vertex: wgpu::VertexState {
                module: shader,
                entry_point: Some("vs_main"),
                buffers: std::slice::from_ref(vertex_buffer_layout),
                compilation_options: Default::default(),
            },
            fragment: Some(wgpu::FragmentState {
                module: shader,
                entry_point: Some("fs_main"),
                targets: &[Some(wgpu::ColorTargetState {
                    format: color_format,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            primitive: wgpu::PrimitiveState {
                topology,
                strip_index_format: None,
                front_face: wgpu::FrontFace::Ccw,
                cull_mode,
                unclipped_depth: false,
                polygon_mode: wgpu::PolygonMode::Fill,
                conservative: false,
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth32Float,
                depth_write_enabled: true,
                depth_compare: wgpu::CompareFunction::Less,
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState {
                count: sample_count,
                mask: !0,
                alpha_to_coverage_enabled: false,
            },
            multiview: None,
            cache: None,
        })
    }
}
