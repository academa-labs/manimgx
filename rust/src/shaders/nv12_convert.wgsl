// RGBA -> NV12 compute shader (BT.601 limited range)
//
// Reads directly from the MSAA texture, manually resolving (averaging) all
// samples per pixel — no intermediate RGBA resolve texture needed.
//
// Each thread handles a 4x2 pixel block: 8 MSAA resolves, 2 packed Y u32 writes,
// 1 packed UV u32 write, zero branching.
// Workgroup: (8,8) -> 32x16 pixels per workgroup.

@group(0) @binding(0) var src: texture_multisampled_2d<f32>;
@group(0) @binding(1) var<storage, read_write> dst: array<u32>;

fn resolve_msaa(x: u32, y: u32) -> vec4<f32> {
    let ns = textureNumSamples(src);
    var acc = vec4<f32>(0.0);
    for (var s = 0i; s < i32(ns); s++) {
        acc += textureLoad(src, vec2<i32>(i32(x), i32(y)), s);
    }
    return acc / f32(ns);
}

fn pack_y4(a: vec4<f32>, b: vec4<f32>, c: vec4<f32>, d: vec4<f32>) -> u32 {
    let ya = u32(clamp(16.0 + 65.481 * a.r + 128.553 * a.g + 24.966 * a.b, 16.0, 235.0));
    let yb = u32(clamp(16.0 + 65.481 * b.r + 128.553 * b.g + 24.966 * b.b, 16.0, 235.0));
    let yc = u32(clamp(16.0 + 65.481 * c.r + 128.553 * c.g + 24.966 * c.b, 16.0, 235.0));
    let yd = u32(clamp(16.0 + 65.481 * d.r + 128.553 * d.g + 24.966 * d.b, 16.0, 235.0));
    return ya | (yb << 8u) | (yc << 16u) | (yd << 24u);
}

fn pack_uv2(avg_l: vec4<f32>, avg_r: vec4<f32>) -> u32 {
    let u0 = u32(clamp(128.0 - 37.797 * avg_l.r - 74.203 * avg_l.g + 112.0 * avg_l.b, 16.0, 240.0));
    let v0 = u32(clamp(128.0 + 112.0 * avg_l.r - 93.786 * avg_l.g - 18.214 * avg_l.b, 16.0, 240.0));
    let u1 = u32(clamp(128.0 - 37.797 * avg_r.r - 74.203 * avg_r.g + 112.0 * avg_r.b, 16.0, 240.0));
    let v1 = u32(clamp(128.0 + 112.0 * avg_r.r - 93.786 * avg_r.g - 18.214 * avg_r.b, 16.0, 240.0));
    return u0 | (v0 << 8u) | (u1 << 16u) | (v1 << 24u);
}

@compute @workgroup_size(8, 8)
fn nv12_convert(@builtin(global_invocation_id) gid: vec3<u32>) {
    let dims = textureDimensions(src);
    let w = dims.x;
    let h = dims.y;

    let px = gid.x * 4u;
    let py = gid.y * 2u;

    if px >= w || py >= h {
        return;
    }

    let py1 = min(py + 1u, h - 1u);

    let r0c0 = resolve_msaa(px,      py );
    let r0c1 = resolve_msaa(px + 1u, py );
    let r0c2 = resolve_msaa(px + 2u, py );
    let r0c3 = resolve_msaa(px + 3u, py );
    let r1c0 = resolve_msaa(px,      py1);
    let r1c1 = resolve_msaa(px + 1u, py1);
    let r1c2 = resolve_msaa(px + 2u, py1);
    let r1c3 = resolve_msaa(px + 3u, py1);

    let y_stride = w / 4u;

    // Y plane — row 0 (always in bounds)
    dst[py * y_stride + gid.x] = pack_y4(r0c0, r0c1, r0c2, r0c3);

    // Y plane — row 1 (guard for odd-height images)
    if py + 1u < h {
        dst[(py + 1u) * y_stride + gid.x] = pack_y4(r1c0, r1c1, r1c2, r1c3);
    }

    // UV plane — always written, no branch
    let avg_l = (r0c0 + r0c1 + r1c0 + r1c1) * 0.25;
    let avg_r = (r0c2 + r0c3 + r1c2 + r1c3) * 0.25;
    let uv_base = w * h / 4u;
    dst[uv_base + gid.y * y_stride + gid.x] = pack_uv2(avg_l, avg_r);
}
