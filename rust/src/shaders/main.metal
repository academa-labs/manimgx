#include <metal_stdlib>
using namespace metal;

struct CameraUniforms {
    float4x4 view_projection;
};

struct DrawUniforms {
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
    float3 position      [[attribute(0)]];
    float3 normal        [[attribute(1)]];
    float2 uv            [[attribute(2)]];
    float4 color         [[attribute(3)]];
};

struct VertexOutput {
    float4 clip_position [[position]];
    float2 uv;
    float4 color;
    float3 world_normal;
};

float3 quat_rotate(float4 q, float3 v) {
    float3 t = 2.0 * cross(q.xyz, v);
    return v + q.w * t + cross(q.xyz, t);
}

vertex VertexOutput vs_main(
    VertexInput in [[stage_in]],
    constant DrawUniforms& draw [[buffer(0)]],
    constant CameraUniforms& camera [[buffer(1)]]
) {
    VertexOutput out;
    float4 q = normalize(draw.rotation);
    float3 scaled = in.position * draw.scale.xyz;
    float3 rotated = quat_rotate(q, scaled);
    float3 world_pos = rotated + draw.position.xyz;
    out.clip_position = camera.view_projection * float4(world_pos, 1.0);
    out.uv = in.uv;
    float3 base_rgb = draw.tint.rgb;
    out.color = float4(base_rgb, in.color.a * draw.opacity);
    // Transform normal: inverse-transpose for non-uniform scale = rotate(n / scale)
    out.world_normal = normalize(quat_rotate(q, in.normal / draw.scale.xyz));
    return out;
}

fragment float4 fs_main(
    VertexOutput in [[stage_in]],
    constant DrawUniforms& draw [[buffer(0)]]
) {
    if (in.uv.x > draw.clip_threshold) {
        discard_fragment();
    }
    if (draw.shading < 0.5) {
        // Unlit: no lighting applied
        return in.color;
    }
    // Flat (shading >= 0.5 && < 1.5) and Smooth (shading >= 1.5) both use Phong
    float3 n = normalize(in.world_normal);
    float3 light_dir = normalize(float3(0.2, 0.3, 1.0));
    float ambient = 0.35;
    float diffuse = max(dot(n, light_dir), 0.0) * 0.55;
    float3 view_dir = float3(0.0, 0.0, 1.0);
    float3 half_vec = normalize(light_dir + view_dir);
    float spec = pow(max(dot(n, half_vec), 0.0), 32.0) * 0.15;
    float brightness = ambient + diffuse + spec;
    return float4(in.color.rgb * brightness, in.color.a);
}
