#include <metal_stdlib>
using namespace metal;

struct CameraUniforms {
    float4x4 view_projection;
};

struct DrawUniforms {
    float4 color;
    float clip_threshold;
    float opacity;
    float shading;
    float _pad0;
    float4 position;
    float4 scale;
    float4 rotation;
    float4 tint;
};

struct VertexInput {
    float3 position [[attribute(0)]];
    float2 uv       [[attribute(1)]];
};

struct VertexOutput {
    float4 clip_position [[position]];
    float2 uv;
    float opacity;
};

float3 quat_rotate_tex(float4 q, float3 v) {
    float3 t = 2.0 * cross(q.xyz, v);
    return v + q.w * t + cross(q.xyz, t);
}

vertex VertexOutput vs_textured(
    VertexInput in [[stage_in]],
    constant DrawUniforms& draw [[buffer(0)]],
    constant CameraUniforms& camera [[buffer(1)]]
) {
    VertexOutput out;
    float4 q = normalize(draw.rotation);
    float3 scaled = in.position * draw.scale.xyz;
    float3 rotated = quat_rotate_tex(q, scaled);
    float3 world_pos = rotated + draw.position.xyz;
    out.clip_position = camera.view_projection * float4(world_pos, 1.0);
    out.uv = in.uv;
    out.opacity = draw.color.a * draw.opacity;
    return out;
}

fragment float4 fs_textured(
    VertexOutput in [[stage_in]],
    texture2d<float> tex [[texture(0)]],
    sampler tex_sampler [[sampler(0)]]
) {
    float4 tex_color = tex.sample(tex_sampler, in.uv);
    return float4(tex_color.rgb, tex_color.a * in.opacity);
}
