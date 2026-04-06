struct CameraUniform {
    view_proj: mat4x4<f32>,
};

struct ObjectUniform {
    model: mat4x4<f32>,
    material_color: vec4<f32>,
    use_vertex_colors: u32,
};

@group(0) @binding(0) var<uniform> camera: CameraUniform;
@group(1) @binding(0) var<uniform> object: ObjectUniform;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) color: vec4<f32>,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) world_normal: vec3<f32>,
    @location(1) color: vec4<f32>,
};

@vertex
fn vs_main(in: VertexInput) -> VertexOutput {
    var out: VertexOutput;
    let world_pos = object.model * vec4<f32>(in.position, 1.0);
    out.clip_position = camera.view_proj * world_pos;
    // Transform normal (ignoring non-uniform scale for simplicity)
    out.world_normal = (object.model * vec4<f32>(in.normal, 0.0)).xyz;
    out.color = in.color;
    return out;
}

@fragment
fn fs_main(@builtin(front_facing) front_facing: bool, in: VertexOutput) -> @location(0) vec4<f32> {
    let light_dir = normalize(vec3<f32>(0.5, 1.0, 0.3));
    var normal = normalize(in.world_normal);
    if (!front_facing) {
        normal = -normal;
    }
    let ndotl = max(dot(normal, light_dir), 0.0);
    let ambient = 0.3;
    let diffuse = ndotl * 0.7;
    let lighting = ambient + diffuse;

    var base_color: vec4<f32>;
    if (object.use_vertex_colors > 0u) {
        base_color = in.color * object.material_color;
    } else {
        base_color = object.material_color;
    }
    return vec4<f32>(base_color.rgb * lighting, base_color.a);
}
