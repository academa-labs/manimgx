struct CameraUniforms {
    view_projection: mat4x4<f32>,
};

struct DrawUniforms {
    clip_threshold: f32,
    opacity: f32,
    shading: f32,
    _pad0: f32,
    position: vec4<f32>,
    scale: vec4<f32>,
    rotation: vec4<f32>,
    tint: vec4<f32>,
};

@group(0) @binding(0) var<uniform> draw: DrawUniforms;
@group(1) @binding(0) var<uniform> camera: CameraUniforms;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) uv: vec2<f32>,
    @location(3) color: vec4<f32>,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) color: vec4<f32>,
    @location(2) world_normal: vec3<f32>,
};

fn quat_rotate(q: vec4<f32>, v: vec3<f32>) -> vec3<f32> {
    let t = 2.0 * cross(q.xyz, v);
    return v + q.w * t + cross(q.xyz, t);
}

@vertex
fn vs_main(in: VertexInput) -> VertexOutput {
    var out: VertexOutput;
    let q = normalize(draw.rotation);
    let scaled = in.position * draw.scale.xyz;
    let rotated = quat_rotate(q, scaled);
    let world_pos = rotated + draw.position.xyz;
    out.clip_position = camera.view_projection * vec4<f32>(world_pos, 1.0);
    out.uv = in.uv;
    let base_rgb = draw.tint.rgb;
    out.color = vec4<f32>(base_rgb, in.color.a * draw.opacity);
    // Transform normal: inverse-transpose for non-uniform scale = rotate(n / scale)
    out.world_normal = normalize(quat_rotate(q, in.normal / draw.scale.xyz));
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    if (in.uv.x > draw.clip_threshold) {
        discard;
    }
    if (draw.shading < 0.5) {
        // Unlit: no lighting applied
        return in.color;
    }
    // Flat (shading >= 0.5 && < 1.5) and Smooth (shading >= 1.5) both use Phong
    let n = normalize(in.world_normal);
    let light_dir = normalize(vec3<f32>(0.2, 0.3, 1.0));
    let ambient = 0.35;
    let diffuse = max(dot(n, light_dir), 0.0) * 0.55;
    let view_dir = vec3<f32>(0.0, 0.0, 1.0);
    let half_vec = normalize(light_dir + view_dir);
    let spec = pow(max(dot(n, half_vec), 0.0), 32.0) * 0.15;
    let brightness = ambient + diffuse + spec;
    return vec4<f32>(in.color.rgb * brightness, in.color.a);
}
