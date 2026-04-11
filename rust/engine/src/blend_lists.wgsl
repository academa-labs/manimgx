// `blend.wgsl`'s see-through lists (where there are storage buffers to append them to): a 3D view's
// see-through fragments, appended per pixel in its raster passes, read by the composite.

@group(0) @binding(7) var<storage, read> sprites: array<vec2<u32>>; // a 3D view's see-through points, far to near: (object, vertex)

// A 3D view's see-through points, six vertices each, in the order `sprites` lists them.
@vertex
fn vs_sprites(@builtin(vertex_index) v: u32) -> Dotted {
    let s = sprites[v / 6u];
    return disk(s.x, s.y, v % 6u);
}

// ── 3D compositing: see-through fragments in depth order, per pixel ────────────────────
//
// A 3D view with see-through layers draws its opaque layers first (depth tested and written).
// Each see-through layer then appends its fragments to a list per pixel: a node per fragment,
// its depth and color at the pixel's center and the samples it covers in front of the opaque
// depth (each tested at its own depth on the fragment's plane). The appends run per sample
// (Metal runs a fragment shader with side effects per sample anyway) and the invocation at a
// fragment's lowest covered sample appends it; a backend that gives each sample only its own
// bit gets a node per sample, the same composite. The view's composite (`vector.wgsl`) lays each
// list's nodes in depth order among its paths and its opaque base: the nodes between two of its
// layers composited sample by sample (a node over the samples it covers), their samples' mean one
// layer. So a pixel shows the depth-ordered composite of every surface on its rays, in any draw
// order: surfaces through surfaces, lines inside a translucent sphere, a cube through a
// translucent floor; exact but where see-through surfaces cross one another inside a pixel
// (ordered there by its center), or where one's edge crosses an opaque edge inside a pixel. One
// object's layer counts once per sample: a stroke's overlapping ribbons as one.
//
// See-through points need no lists to be in depth order: disks facing the camera, sorted far to
// near (`sprites`: among equal depths, the view's order), they composite exactly by blending in
// that order, however many a pixel stacks. So only where the other see-through layers can paint
// (their footprints together) or its paths can (their boxes) are they appended too, and there the
// lists hold every see-through fragment; everywhere else they blend over the opaque samples. A
// view whose only see-through layers are points has no lists.

struct Node {
    depth: f32,
    color: u32, // straight RGBA8
    key: u32,   // record << 11 | samples covered << 3 | winding sign << 2 | kind (0 mesh or points, 3 a mesh's edges)
    next: u32,  // the next node + 1 (0: none)
};

@group(2) @binding(0) var<storage, read_write> heads: array<atomic<u32>>;
@group(2) @binding(1) var<storage, read_write> nodes: array<Node>;
@group(2) @binding(2) var<storage, read_write> appended: atomic<u32>;
@group(2) @binding(3) var opaque_depth: texture_depth_multisampled_2d;
@group(2) @binding(4) var<storage, read> heads_in: array<u32>;
@group(2) @binding(5) var<storage, read> nodes_in: array<Node>;

// Where sample s of n lies from its pixel's center (the standard patterns; others: the center).
fn sample_offset(n: u32, s: u32) -> vec2<f32> {
    if (n == 4u) {
        var four = array<vec2<f32>, 4>(vec2(-2.0, -6.0), vec2(6.0, -2.0), vec2(-6.0, 2.0), vec2(2.0, 6.0));
        return four[s] / 16.0;
    }
    if (n == 8u) {
        var eight = array<vec2<f32>, 8>(vec2(1.0, -3.0), vec2(-1.0, 3.0), vec2(5.0, 1.0), vec2(-3.0, -5.0), vec2(-5.0, 5.0), vec2(-7.0, -1.0), vec2(3.0, 7.0), vec2(7.0, -7.0));
        return eight[s] / 16.0;
    }
    return vec2<f32>(0.0);
}

// A fragment's depth across its pixel (its plane's slopes), taken in uniform control flow.
fn slopes(pos: vec4<f32>) -> vec2<f32> {
    return vec2<f32>(dpdx(pos.z), dpdy(pos.z));
}

// Append a see-through fragment (straight color) over the samples of `mask` it covers in front
// of the opaque depth: once, by the invocation at its lowest covered sample.
fn append(i: u32, pos: vec4<f32>, slope: vec2<f32>, mask: u32, sample: u32, color: vec4<f32>, kind: u32, positive: bool) {
    if (sample != firstTrailingBit(mask) || color.a <= 0.0) {
        return;
    }
    let pixel = vec2<u32>(pos.xy);
    // its depth at the pixel's center (the position may be a sample's)
    let center = pos.z - dot(slope, pos.xy - floor(pos.xy) - vec2<f32>(0.5));
    let n = u32(view.pixels.z);
    var covered = 0u;
    for (var s = 0u; s < n; s += 1u) {
        if ((mask & (1u << s)) != 0u && center + dot(slope, sample_offset(n, s)) > textureLoad(opaque_depth, pixel, s)) {
            covered |= 1u << s;
        }
    }
    if (covered == 0u) {
        return;
    }
    let k = atomicAdd(&appended, 1u);
    if (k >= arrayLength(&nodes)) {
        return; // full: the count tells the player to draw the frame again with more room
    }
    let key = ((ids_of(i).z >> 8u) << 11u) | (covered << 3u) | select(0u, 4u, positive) | kind;
    let next = atomicExchange(&heads[pixel.y * u32(view.pixels.x) + pixel.x], k + 1u);
    nodes[k] = Node(center, pack4x8unorm(color), key, next);
}

fn straight(c: vec4<f32>) -> vec4<f32> {
    return vec4<f32>(c.rgb / max(c.a, 1e-6), c.a);
}

@fragment
fn fs_stroke_append(in: Stroked, @builtin(sample_mask) mask: u32, @builtin(sample_index) sample: u32) {
    let slope = slopes(in.position);
    if (in.u < in.window.x || in.u > in.window.y) {
        return;
    }
    append(in.i, in.position, slope, mask, sample, in.color, 3u, true);
}

@fragment
fn fs_stroke_gradient_append(in: Stroked, @builtin(sample_mask) mask: u32, @builtin(sample_index) sample: u32) {
    let slope = slopes(in.position);
    if (in.u < in.window.x || in.u > in.window.y) {
        return;
    }
    let c = gradient(in.i, brush_of(in.i).z, brush2_of(in.i).y, brush_of(in.i).w, in.t, extra_of(in.i).y);
    append(in.i, in.position, slope, mask, sample, c, 3u, true);
}

@fragment
fn fs_mesh_append(in: Shaded, @builtin(sample_mask) mask: u32, @builtin(sample_index) sample: u32) {
    append(in.i, in.position, slopes(in.position), mask, sample, straight(shaded(in)), 0u, true);
}

@fragment
fn fs_points_append(in: Dotted, @builtin(sample_mask) mask: u32, @builtin(sample_index) sample: u32) {
    append(in.i, in.position, slopes(in.position), mask, sample, dot_color(in), 0u, true);
}

// A sprite where no see-through fragment is listed: blended over whatever is farther (a read of
// the heads, not an atomic: a shader with side effects would run per sample).
fn sprite_unlisted(in: Dotted) -> vec4<f32> {
    let c = dot_color(in);
    let pixel = vec2<u32>(in.position.xy);
    if (c.a <= 0.0 || heads_in[pixel.y * u32(view.pixels.x) + pixel.x] != 0u) {
        discard;
    }
    return premultiplied(c);
}

@fragment
fn fs_sprites_unlisted(in: Dotted) -> @location(0) vec4<f32> {
    return sprite_unlisted(in);
}

@fragment
fn fs_sprites_unlisted_with_light(in: Dotted) -> Base {
    return painted(sprite_unlisted(in));
}
