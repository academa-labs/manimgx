// RGBA -> NV12 compute kernel (BT.601 limited range)
//
// Reads directly from the MSAA texture, manually resolving (averaging) all
// samples per pixel — no intermediate RGBA resolve texture needed.
//
// Each thread handles a 4x2 pixel block: 8 MSAA resolves, 2 packed Y u32 writes,
// 1 packed UV u32 write, zero branching.
// Workgroup: (16,16), dispatched as (ceil(w/64), ceil(h/32)) groups.

#include <metal_stdlib>
using namespace metal;

inline float4 resolve_pixel(texture2d_ms<float, access::read> src, uint x, uint y) {
    uint ns = src.get_num_samples();
    float4 acc = float4(0.0f);
    for (uint s = 0; s < ns; s++) {
        acc += src.read(uint2(x, y), s);
    }
    return acc / float(ns);
}

inline uint pack_y4(float4 a, float4 b, float4 c, float4 d) {
    uint ya = uint(clamp(16.0f + 65.481f * a.r + 128.553f * a.g + 24.966f * a.b, 16.0f, 235.0f));
    uint yb = uint(clamp(16.0f + 65.481f * b.r + 128.553f * b.g + 24.966f * b.b, 16.0f, 235.0f));
    uint yc = uint(clamp(16.0f + 65.481f * c.r + 128.553f * c.g + 24.966f * c.b, 16.0f, 235.0f));
    uint yd = uint(clamp(16.0f + 65.481f * d.r + 128.553f * d.g + 24.966f * d.b, 16.0f, 235.0f));
    return ya | (yb << 8) | (yc << 16) | (yd << 24);
}

inline uint pack_uv2(float4 avg_l, float4 avg_r) {
    uint u0 = uint(clamp(128.0f - 37.797f * avg_l.r - 74.203f * avg_l.g + 112.0f * avg_l.b, 16.0f, 240.0f));
    uint v0 = uint(clamp(128.0f + 112.0f * avg_l.r - 93.786f * avg_l.g - 18.214f * avg_l.b, 16.0f, 240.0f));
    uint u1 = uint(clamp(128.0f - 37.797f * avg_r.r - 74.203f * avg_r.g + 112.0f * avg_r.b, 16.0f, 240.0f));
    uint v1 = uint(clamp(128.0f + 112.0f * avg_r.r - 93.786f * avg_r.g - 18.214f * avg_r.b, 16.0f, 240.0f));
    return u0 | (v0 << 8) | (u1 << 16) | (v1 << 24);
}

kernel void nv12_convert(
    texture2d_ms<float, access::read> src [[texture(0)]],
    device uint32_t* dst                  [[buffer(0)]],
    uint2 gid [[thread_position_in_grid]]
) {
    uint w = src.get_width();
    uint h = src.get_height();

    uint px = gid.x * 4;
    uint py = gid.y * 2;

    if (px >= w || py >= h) {
        return;
    }

    uint py1 = min(py + 1, h - 1);

    float4 r0c0 = resolve_pixel(src, px,     py );
    float4 r0c1 = resolve_pixel(src, px + 1, py );
    float4 r0c2 = resolve_pixel(src, px + 2, py );
    float4 r0c3 = resolve_pixel(src, px + 3, py );
    float4 r1c0 = resolve_pixel(src, px,     py1);
    float4 r1c1 = resolve_pixel(src, px + 1, py1);
    float4 r1c2 = resolve_pixel(src, px + 2, py1);
    float4 r1c3 = resolve_pixel(src, px + 3, py1);

    uint y_stride = w / 4;

    // Y plane — row 0 (always in bounds)
    dst[py * y_stride + gid.x] = pack_y4(r0c0, r0c1, r0c2, r0c3);

    // Y plane — row 1 (guard for odd-height images)
    if (py + 1 < h) {
        dst[(py + 1) * y_stride + gid.x] = pack_y4(r1c0, r1c1, r1c2, r1c3);
    }

    // UV plane — always written, no branch
    float4 avg_l = (r0c0 + r0c1 + r1c0 + r1c1) * 0.25f;
    float4 avg_r = (r0c2 + r0c3 + r1c2 + r1c3) * 0.25f;
    dst[w * h / 4 + gid.y * y_stride + gid.x] = pack_uv2(avg_l, avg_r);
}
