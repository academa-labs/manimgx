// 3D lit shading — port of default.wgsl.
// Diffuse + ambient lighting, double-sided via [[front_facing]].

#include "types.h"

struct VertexOut {
    float4 position [[position]];
    float3 world_normal;
    float4 color;
};

vertex VertexOut vs_main(
    VertexIn in [[stage_in]],
    constant CameraUniform& camera [[buffer(1)]],
    constant ObjectUniform& object [[buffer(2)]]
) {
    VertexOut out;
    float4 world_pos = object.model * float4(in.position, 1.0);
    out.position = camera.view_proj * world_pos;
    out.world_normal = (object.model * float4(in.normal, 0.0)).xyz;
    out.color = in.color;
    return out;
}

fragment float4 fs_main(
    VertexOut in [[stage_in]],
    bool front_facing [[front_facing]],
    constant ObjectUniform& object [[buffer(2)]]
) {
    float3 light_dir = normalize(float3(0.5, 1.0, 0.3));
    float3 normal = normalize(in.world_normal);
    if (!front_facing) {
        normal = -normal;
    }
    float ndotl = max(dot(normal, light_dir), 0.0);
    float ambient = 0.3;
    float diffuse = ndotl * 0.7;
    float lighting = ambient + diffuse;

    float4 base_color;
    if (object.use_vertex_colors > 0u) {
        base_color = in.color * object.material_color;
    } else {
        base_color = object.material_color;
    }
    return float4(base_color.rgb * lighting, base_color.a);
}
