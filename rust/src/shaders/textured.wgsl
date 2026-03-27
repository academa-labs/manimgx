struct CameraUniforms {
    view_projection: mat4x4<f32>,
};

struct DrawUniforms {
    color: vec4<f32>,
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
@group(2) @binding(0) var tex: texture_2d<f32>;
@group(2) @binding(1) var tex_sampler: sampler;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) uv: vec2<f32>,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) uv: vec2<f32>,
    @location(1) opacity: f32,
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
    out.opacity = draw.color.a * draw.opacity;
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let tex_color = textureSample(tex, tex_sampler, in.uv);
    return vec4<f32>(tex_color.rgb, tex_color.a * in.opacity);
}
