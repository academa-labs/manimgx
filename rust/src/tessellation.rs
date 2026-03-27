use lyon::math::point;
use lyon::path::Path as LyonPath;
use lyon::tessellation::*;
use pyo3::prelude::*;

use crate::render_context::{FillRule as PyFillRule, Shading, Side};

#[pyclass(skip_from_py_object)]
#[derive(Clone)]
pub struct SubMesh {
    /// Flat vertex positions [x0, y0, z0, x1, y1, z1, ...], f32
    #[pyo3(get)]
    pub positions: Vec<f32>,
    /// Flat vertex normals [nx0, ny0, nz0, nx1, ny1, nz1, ...], f32
    #[pyo3(get)]
    pub normals: Vec<f32>,
    /// Per-vertex progress (arc-length fraction 0..1), f32
    #[pyo3(get, set)]
    pub progress: Vec<f32>,
    /// RGBA color [r, g, b, a] normalized 0..1
    #[pyo3(get)]
    pub color: [f32; 4],
    /// Triangle indices, u32
    #[pyo3(get)]
    pub indices: Vec<u32>,
    /// 0 = fill, 1 = stroke
    #[pyo3(get)]
    pub kind: u32,
    /// Index of the SVG path this submesh was tessellated from
    #[pyo3(get)]
    pub path_index: u32,
    /// Per-vertex RGBA colors, flat [r0,g0,b0,a0, r1,g1,b1,a1, ...].
    /// When empty, `color` is used as a uniform fallback for every vertex.
    #[pyo3(get)]
    pub colors: Vec<f32>,
    /// Whether this submesh should be lit (1.0) or unlit (0.0)
    pub use_lighting: f32,
}

struct PathData {
    lyon_path: LyonPath,
    color: [f32; 4],
    arc_length: f32,
}

// ── Mesh ─────────────────────────────────────────────────────────────

/// Immutable vertex/index data produced by tessellation.
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct Mesh {
    #[pyo3(get)]
    pub submeshes: Vec<SubMesh>,
    /// Per-path arc lengths (one entry per SVG path that produced a submesh)
    #[pyo3(get)]
    pub arc_lengths: Vec<f32>,
    /// Bounding box after normalization [min_x, min_y, min_z, max_x, max_y, max_z]
    #[pyo3(get)]
    pub bounds: [f32; 6],

    // Texture quad geometry — separate from SubMesh pipeline.
    // Populated by build_textured_quad (pixel data lives in Texture).
    /// Flat vertex positions for the textured quad [x0,y0,z0, x1,y1,z1, ...]
    pub texture_positions: Vec<f32>,
    /// Flat UV coordinates [u0,v0, u1,v1, ...]
    pub texture_uvs: Vec<f32>,
    /// Triangle indices for the textured quad
    pub texture_indices: Vec<u32>,
}

#[pymethods]
impl Mesh {
    #[staticmethod]
    fn empty() -> Self {
        Mesh {
            submeshes: Vec::new(),
            arc_lengths: Vec::new(),
            bounds: [0.0; 6],
            texture_positions: Vec::new(),
            texture_uvs: Vec::new(),
            texture_indices: Vec::new(),
        }
    }

    #[getter]
    fn submesh_count(&self) -> usize {
        self.submeshes.len()
    }

    fn get_submesh_kind(&self, index: usize) -> u32 {
        self.submeshes[index].kind
    }

    fn get_submesh_progress(&self, index: usize) -> Vec<f32> {
        self.submeshes[index].progress.clone()
    }

    fn get_submesh_path_index(&self, index: usize) -> u32 {
        self.submeshes[index].path_index
    }

    fn set_submesh_progress(&mut self, index: usize, progress: Vec<f32>) {
        self.submeshes[index].progress = progress;
    }
}

// ── TessellationResult ──────────────────────────────────────────────

/// Result of tessellation: separate fill and stroke meshes.
#[pyclass]
pub struct TessellationResult {
    #[pyo3(get)]
    pub fill_mesh: Option<Py<Mesh>>,
    #[pyo3(get)]
    pub stroke_mesh: Option<Py<Mesh>>,
    /// Per-path arc lengths for coordinating draw progress across fill+stroke
    pub arc_lengths: Vec<f32>,
}

#[pymethods]
impl TessellationResult {}

// ── Texture ──────────────────────────────────────────────────────────

/// Opaque handle to GPU texture data (pixel frames).
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct Texture {
    pub frames: Vec<Vec<u8>>,
    pub width: u32,
    pub height: u32,
}

// ── Material ─────────────────────────────────────────────────────────

/// Surface appearance properties. Stored on Surface and read per-frame
/// by the snapshot/render pipeline.
#[pyclass]
pub struct Material {
    #[pyo3(get, set)]
    pub color: (u8, u8, u8),
    #[pyo3(get, set)]
    pub opacity: f32,
    #[pyo3(get, set)]
    pub shading: Shading,
    #[pyo3(get, set)]
    pub metallic: f32,
    #[pyo3(get, set)]
    pub roughness: f32,
    #[pyo3(get, set)]
    pub emissive: (u8, u8, u8),
    #[pyo3(get, set)]
    pub side: Side,
    pub(crate) texture: Option<Py<Texture>>,
}

#[pymethods]
impl Material {
    #[new]
    #[pyo3(signature = (*, color=(255, 255, 255), opacity=1.0, shading=None, side=None, texture=None, metallic=0.0, roughness=0.5, emissive=(0, 0, 0)))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        color: (u8, u8, u8),
        opacity: f32,
        shading: Option<Shading>,
        side: Option<Side>,
        texture: Option<Py<Texture>>,
        metallic: f32,
        roughness: f32,
        emissive: (u8, u8, u8),
    ) -> Self {
        Material {
            color,
            opacity,
            shading: shading.unwrap_or(Shading { value: 0 }),
            side: side.unwrap_or(Side { value: 0 }),
            texture,
            metallic,
            roughness,
            emissive,
        }
    }

    #[getter]
    fn texture(&self, py: Python<'_>) -> Option<Py<Texture>> {
        self.texture.as_ref().map(|t| t.clone_ref(py))
    }

    #[setter]
    fn set_texture(&mut self, value: Option<Py<Texture>>) {
        self.texture = value;
    }
}

// ── Surface ──────────────────────────────────────────────────────────

/// Geometry + appearance — **what to draw**.
///
/// Pairs a Mesh with a Material. Carries no transform of its own.
/// Attach to an Object3D (which controls *where* it is drawn).
/// Swapping the `mesh` reference triggers a GPU re-upload via the
/// generation counter.
#[pyclass]
pub struct Surface {
    pub(crate) mesh: Py<Mesh>,
    pub(crate) material: Py<Material>,
    #[pyo3(get, set)]
    pub active: bool,
    #[pyo3(get, set)]
    pub z_index: f32,
    /// Internal: the fragment shader discards pixels where u > clip_threshold.
    /// Always 1.0 (fully active). Progressive reveal will be reimplemented
    /// without leaking GPU concerns into the public API.
    pub clip_threshold: f32,
    /// Incremented when mesh is swapped. Renderer uses this to detect
    /// when vertex buffers need re-upload.
    pub generation: u32,
}

#[pymethods]
impl Surface {
    #[new]
    fn new(mesh: Py<Mesh>, material: Py<Material>) -> Self {
        Surface {
            mesh,
            material,
            active: true,
            z_index: 0.0,
            clip_threshold: 1.0,
            generation: 0,
        }
    }

    #[getter]
    fn mesh(&self, py: Python<'_>) -> Py<Mesh> {
        self.mesh.clone_ref(py)
    }

    #[setter]
    fn set_mesh(&mut self, m: Py<Mesh>) {
        self.mesh = m;
        self.generation += 1;
    }

    #[getter]
    fn material(&self, py: Python<'_>) -> Py<Material> {
        self.material.clone_ref(py)
    }

    #[setter]
    fn set_material(&mut self, mat: Py<Material>) {
        self.material = mat;
    }
}

// ── SVG Glyph Data ──────────────────────────────────────────────────

/// Per-glyph tessellation result from SVG. Each SVG path produces one glyph.
#[pyclass]
pub struct SvgGlyphData {
    #[pyo3(get)]
    pub fill_mesh: Option<Py<Mesh>>,
    #[pyo3(get)]
    pub stroke_mesh: Option<Py<Mesh>>,
    #[pyo3(get)]
    pub color: (u8, u8, u8),
}

/// Tracks which submesh indices belong to which glyph during SVG tessellation.
struct SvgGlyphRange {
    fill_start: usize,
    fill_count: usize,
    stroke_path_index: Option<usize>, // index into path_data for auto-stroke
    color: [f32; 4],
}

/// Tessellate an SVG document into per-glyph meshes.
/// Each SVG path becomes a separate SvgGlyphData with its own fill and stroke meshes.
#[pyfunction]
pub fn tessellate_svg(py: Python<'_>, svg_bytes: &[u8]) -> PyResult<Vec<SvgGlyphData>> {
    let options = usvg::Options::default();
    let tree = usvg::Tree::from_data(svg_bytes, &options)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("SVG parse error: {e}")))?;

    let mut fills: Vec<SubMesh> = Vec::new();
    let mut path_data: Vec<PathData> = Vec::new();
    let mut glyph_ranges: Vec<SvgGlyphRange> = Vec::new();
    walk_group_tracked(tree.root(), &mut fills, &mut path_data, &mut glyph_ranges);

    // Auto-stroke width from combined fill bbox height
    let bbox_height = if fills.is_empty() {
        1.0
    } else {
        let (_, min_y, _, _, max_y, _) = compute_bbox(&fills);
        let h = max_y - min_y;
        if h > 1e-9 { h } else { 1.0 }
    };
    let auto_sw = bbox_height * 0.008;

    // Generate auto-strokes (one per glyph that has path_data)
    let mut auto_strokes: Vec<Option<SubMesh>> = vec![None; glyph_ranges.len()];
    for (gi, range) in glyph_ranges.iter().enumerate() {
        if let Some(pdi) = range.stroke_path_index
            && let Some(mut sm) = tessellate_stroke(&path_data[pdi], auto_sw)
        {
            sm.path_index = pdi as u32;
            auto_strokes[gi] = Some(sm);
        }
    }

    // Compute combined bbox from fills + auto_strokes without cloning
    let mut combined_bbox = compute_bbox(&fills);
    for sm in auto_strokes.iter().flatten() {
        combined_bbox = extend_bbox(combined_bbox, sm);
    }
    if combined_bbox.0 == f32::MAX {
        combined_bbox = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
    }

    // Normalize everything against the shared bbox (in place)
    normalize_submeshes_with_ref(&mut fills, combined_bbox);
    for sm in auto_strokes.iter_mut().flatten() {
        normalize_submeshes_with_ref(std::slice::from_mut(sm), combined_bbox);
    }

    // Compute bounds from all normalized submeshes without cloning
    let mut norm_bbox = compute_bbox(&fills);
    for sm in auto_strokes.iter().flatten() {
        norm_bbox = extend_bbox(norm_bbox, sm);
    }
    let bounds = if norm_bbox.0 != f32::MAX {
        bbox_to_bounds(norm_bbox)
    } else {
        [0.0; 6]
    };

    // Build per-glyph Mesh objects
    let make_mesh = |submeshes: Vec<SubMesh>, arc_lens: Vec<f32>| -> Mesh {
        Mesh {
            submeshes,
            arc_lengths: arc_lens,
            bounds, // shared bounds for all glyphs
            texture_positions: Vec::new(),
            texture_uvs: Vec::new(),
            texture_indices: Vec::new(),
        }
    };

    let mut result: Vec<SvgGlyphData> = Vec::new();
    for (gi, range) in glyph_ranges.iter().enumerate() {
        let glyph_fills: Vec<SubMesh> =
            fills[range.fill_start..range.fill_start + range.fill_count].to_vec();
        let glyph_arc_lengths: Vec<f32> = glyph_fills
            .iter()
            .filter_map(|sm| {
                path_data
                    .get(sm.path_index as usize)
                    .map(|pd| pd.arc_length)
            })
            .collect();

        let fill_mesh = if glyph_fills.is_empty() {
            None
        } else {
            Some(Py::new(
                py,
                make_mesh(glyph_fills, glyph_arc_lengths.clone()),
            )?)
        };

        let stroke_mesh = if let Some(stroke_sm) = auto_strokes[gi].take() {
            Some(Py::new(py, make_mesh(vec![stroke_sm], glyph_arc_lengths))?)
        } else {
            None
        };

        let c = range.color;
        let color = (
            (c[0] * 255.0).round() as u8,
            (c[1] * 255.0).round() as u8,
            (c[2] * 255.0).round() as u8,
        );

        result.push(SvgGlyphData {
            fill_mesh,
            stroke_mesh,
            color,
        });
    }

    Ok(result)
}

fn walk_group_tracked(
    group: &usvg::Group,
    fills: &mut Vec<SubMesh>,
    path_data: &mut Vec<PathData>,
    glyph_ranges: &mut Vec<SvgGlyphRange>,
) {
    for child in group.children() {
        match child {
            usvg::Node::Group(g) => walk_group_tracked(g, fills, path_data, glyph_ranges),
            usvg::Node::Path(path) => {
                let fill_start = fills.len();
                let pd_start = path_data.len();

                // Use existing tessellate_usvg_path to populate fills and path_data
                tessellate_usvg_path(path, fills, path_data);

                let fill_count = fills.len() - fill_start;
                let stroke_path_index = if path_data.len() > pd_start {
                    Some(pd_start)
                } else {
                    None
                };

                // Extract color from the fill submesh or use white default
                let color = if fill_count > 0 {
                    fills[fill_start].color
                } else {
                    [1.0, 1.0, 1.0, 1.0]
                };

                if fill_count > 0 || stroke_path_index.is_some() {
                    glyph_ranges.push(SvgGlyphRange {
                        fill_start,
                        fill_count,
                        stroke_path_index,
                        color,
                    });
                }
            }
            _ => {} // Skip Image, Text
        }
    }
}

fn tessellate_usvg_path(
    path: &usvg::Path,
    fills: &mut Vec<SubMesh>,
    path_data: &mut Vec<PathData>,
) {
    let (segments, total_length) = collect_segments_with_length(path.data(), path.abs_transform());
    let (lyon_path, arc_length) = build_lyon_path_from_segments(&segments, total_length);

    // Handle fill
    if let Some(fill) = path.fill()
        && let Some(color) = extract_fill_color(fill)
    {
        let fill_rule = match fill.rule() {
            usvg::FillRule::NonZero => FillRule::NonZero,
            usvg::FillRule::EvenOdd => FillRule::EvenOdd,
        };

        let options = FillOptions::default().with_fill_rule(fill_rule);

        // Vertex type: [x, y, progress]
        let mut geometry: VertexBuffers<[f32; 3], u32> = VertexBuffers::new();
        let mut tessellator = FillTessellator::new();

        let result = tessellator.tessellate_path(
            &lyon_path,
            &options,
            &mut BuffersBuilder::new(&mut geometry, |mut vertex: FillVertex| {
                let pos = vertex.position();
                let progress = vertex.interpolated_attributes()[0];
                [pos.x, pos.y, progress]
            }),
        );

        if let Ok(()) = result
            && !geometry.indices.is_empty()
        {
            // Assign chord-closure progress: each fill vertex gets the minimum
            // clip_threshold at which it falls inside the chord-closed partial
            // path, matching manim CE's pointwise_become_partial fill.
            let boundary = sample_boundary_points(&segments, total_length);
            assign_fill_chord_progress(&mut geometry.vertices, &boundary);

            let num_verts = geometry.vertices.len();
            let positions: Vec<f32> = geometry
                .vertices
                .iter()
                .flat_map(|v| [v[0], v[1], 0.0])
                .collect();
            let normals: Vec<f32> = [0.0, 0.0, 1.0].repeat(num_verts);
            let progress: Vec<f32> = geometry.vertices.iter().map(|v| v[2]).collect();
            let pi = path_data.len() as u32;

            fills.push(SubMesh {
                positions,
                normals,
                progress,
                color,
                indices: geometry.indices,
                kind: 0,
                path_index: pi,
                colors: Vec::new(),
                use_lighting: 0.0,
            });

            // Store path for auto-stroke tessellation
            path_data.push(PathData {
                lyon_path: lyon_path.clone(),
                color,
                arc_length,
            });
        }
    }

    // Handle explicit SVG stroke (e.g. from Typst text stroke settings).
    // These are treated as fills (kind=0) so they render with fill_opacity
    // and aren't hidden when stroke_opacity is set to 0.
    if let Some(stroke) = path.stroke()
        && let Some(color) = extract_stroke_color(stroke)
    {
        let line_cap = match stroke.linecap() {
            usvg::LineCap::Butt => LineCap::Butt,
            usvg::LineCap::Round => LineCap::Round,
            usvg::LineCap::Square => LineCap::Square,
        };
        let line_join = match stroke.linejoin() {
            usvg::LineJoin::Miter | usvg::LineJoin::MiterClip => LineJoin::Miter,
            usvg::LineJoin::Round => LineJoin::Round,
            usvg::LineJoin::Bevel => LineJoin::Bevel,
        };
        let width = stroke.width().get();

        let options = StrokeOptions::default()
            .with_line_width(width)
            .with_line_cap(line_cap)
            .with_line_join(line_join)
            .with_miter_limit(stroke.miterlimit().get());

        let mut geometry: VertexBuffers<[f32; 3], u32> = VertexBuffers::new();
        let mut tessellator = StrokeTessellator::new();

        let result = tessellator.tessellate_path(
            &lyon_path,
            &options,
            &mut BuffersBuilder::new(&mut geometry, |mut vertex: StrokeVertex| {
                let pos = vertex.position();
                let progress = vertex.interpolated_attributes()[0];
                [pos.x, pos.y, progress]
            }),
        );

        if let Ok(()) = result
            && !geometry.indices.is_empty()
        {
            let num_verts = geometry.vertices.len();
            let positions: Vec<f32> = geometry
                .vertices
                .iter()
                .flat_map(|v| [v[0], v[1], 0.0])
                .collect();
            let normals: Vec<f32> = [0.0, 0.0, 1.0].repeat(num_verts);
            let progress: Vec<f32> = geometry.vertices.iter().map(|v| v[2]).collect();
            let pi = if path_data.is_empty() {
                0
            } else {
                path_data.len() as u32 - 1
            };

            fills.push(SubMesh {
                positions,
                normals,
                progress,
                color,
                indices: geometry.indices,
                kind: 0, // Treat as fill so it's not affected by stroke_opacity
                path_index: pi,
                colors: Vec::new(),
                use_lighting: 0.0,
            });
        }
    }
}

type BBox = (f32, f32, f32, f32, f32, f32);

const EMPTY_BBOX: BBox = (f32::MAX, f32::MAX, f32::MAX, f32::MIN, f32::MIN, f32::MIN);

fn compute_bbox(submeshes: &[SubMesh]) -> BBox {
    let mut bb = EMPTY_BBOX;
    for sm in submeshes {
        bb = extend_bbox(bb, sm);
    }
    bb
}

/// Extend a bounding box with a single submesh's positions.
fn extend_bbox(bb: BBox, sm: &SubMesh) -> BBox {
    let (mut min_x, mut min_y, mut min_z, mut max_x, mut max_y, mut max_z) = bb;
    for i in (0..sm.positions.len()).step_by(3) {
        let x = sm.positions[i];
        let y = sm.positions[i + 1];
        let z = sm.positions[i + 2];
        min_x = min_x.min(x);
        min_y = min_y.min(y);
        min_z = min_z.min(z);
        max_x = max_x.max(x);
        max_y = max_y.max(y);
        max_z = max_z.max(z);
    }
    (min_x, min_y, min_z, max_x, max_y, max_z)
}

/// Merge two bounding boxes into the smallest box containing both.
fn merge_bboxes(a: BBox, b: BBox) -> BBox {
    (
        a.0.min(b.0),
        a.1.min(b.1),
        a.2.min(b.2),
        a.3.max(b.3),
        a.4.max(b.4),
        a.5.max(b.5),
    )
}

fn bbox_to_bounds(bb: BBox) -> [f32; 6] {
    let (min_x, min_y, min_z, max_x, max_y, max_z) = bb;
    [min_x, min_y, min_z, max_x, max_y, max_z]
}

/// Stroke with miter joins (sharp corners) for explicit user-requested strokes.
fn tessellate_stroke_miter(pd: &PathData, stroke_width: f32) -> Option<SubMesh> {
    let options = StrokeOptions::default()
        .with_line_width(stroke_width)
        .with_line_cap(LineCap::Butt)
        .with_line_join(LineJoin::Miter)
        .with_miter_limit(4.0)
        .with_tolerance(0.005);

    let mut geometry: VertexBuffers<[f32; 3], u32> = VertexBuffers::new();
    let mut tessellator = StrokeTessellator::new();

    let result = tessellator.tessellate_path(
        &pd.lyon_path,
        &options,
        &mut BuffersBuilder::new(&mut geometry, |mut vertex: StrokeVertex| {
            let pos = vertex.position();
            let progress = vertex.interpolated_attributes()[0];
            [pos.x, pos.y, progress]
        }),
    );

    if let Ok(()) = result
        && !geometry.indices.is_empty()
    {
        let num_verts = geometry.vertices.len();
        let positions: Vec<f32> = geometry
            .vertices
            .iter()
            .flat_map(|v| [v[0], v[1], 0.0])
            .collect();
        let normals: Vec<f32> = [0.0, 0.0, 1.0].repeat(num_verts);
        let progress: Vec<f32> = geometry.vertices.iter().map(|v| v[2]).collect();

        Some(SubMesh {
            positions,
            normals,
            progress,
            color: pd.color,
            indices: geometry.indices,
            kind: 1,
            path_index: 0,
            colors: Vec::new(),
            use_lighting: 0.0,
        })
    } else {
        None
    }
}

/// Stroke with round joins/caps for auto-stroke outlines.
fn tessellate_stroke(pd: &PathData, stroke_width: f32) -> Option<SubMesh> {
    let options = StrokeOptions::default()
        .with_line_width(stroke_width)
        .with_line_cap(LineCap::Round)
        .with_line_join(LineJoin::Round)
        .with_tolerance(0.005);

    let mut geometry: VertexBuffers<[f32; 3], u32> = VertexBuffers::new();
    let mut tessellator = StrokeTessellator::new();

    let result = tessellator.tessellate_path(
        &pd.lyon_path,
        &options,
        &mut BuffersBuilder::new(&mut geometry, |mut vertex: StrokeVertex| {
            let pos = vertex.position();
            let progress = vertex.interpolated_attributes()[0];
            [pos.x, pos.y, progress]
        }),
    );

    if let Ok(()) = result
        && !geometry.indices.is_empty()
    {
        let num_verts = geometry.vertices.len();
        let positions: Vec<f32> = geometry
            .vertices
            .iter()
            .flat_map(|v| [v[0], v[1], 0.0])
            .collect();
        let normals: Vec<f32> = [0.0, 0.0, 1.0].repeat(num_verts);
        let progress: Vec<f32> = geometry.vertices.iter().map(|v| v[2]).collect();

        Some(SubMesh {
            positions,
            normals,
            progress,
            color: pd.color,
            indices: geometry.indices,
            kind: 1,
            path_index: 0, // Set by caller
            colors: Vec::new(),
            use_lighting: 0.0,
        })
    } else {
        None
    }
}

fn extract_fill_color(fill: &usvg::Fill) -> Option<[f32; 4]> {
    match fill.paint() {
        usvg::Paint::Color(c) => {
            let opacity = fill.opacity().get();
            Some([
                c.red as f32 / 255.0,
                c.green as f32 / 255.0,
                c.blue as f32 / 255.0,
                opacity,
            ])
        }
        _ => None, // Skip gradients, patterns for now
    }
}

fn extract_stroke_color(stroke: &usvg::Stroke) -> Option<[f32; 4]> {
    match stroke.paint() {
        usvg::Paint::Color(c) => {
            let opacity = stroke.opacity().get();
            Some([
                c.red as f32 / 255.0,
                c.green as f32 / 255.0,
                c.blue as f32 / 255.0,
                opacity,
            ])
        }
        _ => None,
    }
}

/// Build a lyon Path from pre-collected path segments with arc-length progress.
fn build_lyon_path_from_segments(
    segments: &[(PathSeg, f32)],
    total_length: f32,
) -> (LyonPath, f32) {
    let mut builder = LyonPath::builder_with_attributes(1);
    let progress = |cum: f32| -> f32 {
        if total_length > 0.0 {
            cum / total_length
        } else {
            0.0
        }
    };

    let mut has_open_path = false;
    for (seg, cum) in segments {
        let p = progress(*cum);
        match seg {
            PathSeg::MoveTo(x, y) => {
                if has_open_path {
                    builder.end(false);
                }
                builder.begin(point(*x, *y), &[p]);
                has_open_path = true;
            }
            PathSeg::LineTo(x, y) => {
                builder.line_to(point(*x, *y), &[p]);
            }
            PathSeg::CubicTo(c1x, c1y, c2x, c2y, ex, ey) => {
                builder.cubic_bezier_to(
                    point(*c1x, *c1y),
                    point(*c2x, *c2y),
                    point(*ex, *ey),
                    &[p],
                );
            }
            PathSeg::QuadTo(cx, cy, ex, ey) => {
                builder.quadratic_bezier_to(point(*cx, *cy), point(*ex, *ey), &[p]);
            }
            PathSeg::Close => {
                builder.end(true);
                has_open_path = false;
            }
        }
    }

    if has_open_path {
        builder.end(false);
    }

    (builder.build(), total_length)
}

enum PathSeg {
    MoveTo(f32, f32),
    LineTo(f32, f32),
    CubicTo(f32, f32, f32, f32, f32, f32),
    QuadTo(f32, f32, f32, f32),
    Close,
}

fn collect_segments_with_length(
    data: &usvg::tiny_skia_path::Path,
    transform: usvg::Transform,
) -> (Vec<(PathSeg, f32)>, f32) {
    let mut segments: Vec<(PathSeg, f32)> = Vec::new();
    let mut cumulative = 0.0f32;
    let mut last: Option<(f32, f32)> = None;

    for seg in data.segments() {
        match seg {
            usvg::tiny_skia_path::PathSegment::MoveTo(pt) => {
                let (x, y) = apply_transform(pt.x, pt.y, transform);
                // MoveTo adds no arc length; store cumulative before the move.
                segments.push((PathSeg::MoveTo(x, y), cumulative));
                last = Some((x, y));
            }
            usvg::tiny_skia_path::PathSegment::LineTo(pt) => {
                let (x, y) = apply_transform(pt.x, pt.y, transform);
                if let Some((lx, ly)) = last {
                    let dx = x - lx;
                    let dy = y - ly;
                    cumulative += (dx * dx + dy * dy).sqrt();
                }
                segments.push((PathSeg::LineTo(x, y), cumulative));
                last = Some((x, y));
            }
            usvg::tiny_skia_path::PathSegment::CubicTo(pt1, pt2, pt3) => {
                let (c1x, c1y) = apply_transform(pt1.x, pt1.y, transform);
                let (c2x, c2y) = apply_transform(pt2.x, pt2.y, transform);
                let (ex, ey) = apply_transform(pt3.x, pt3.y, transform);
                if let Some((lx, ly)) = last {
                    cumulative += cubic_arc_length(lx, ly, c1x, c1y, c2x, c2y, ex, ey);
                }
                segments.push((PathSeg::CubicTo(c1x, c1y, c2x, c2y, ex, ey), cumulative));
                last = Some((ex, ey));
            }
            usvg::tiny_skia_path::PathSegment::QuadTo(pt1, pt2) => {
                let (cx, cy) = apply_transform(pt1.x, pt1.y, transform);
                let (ex, ey) = apply_transform(pt2.x, pt2.y, transform);
                if let Some((lx, ly)) = last {
                    cumulative += quad_arc_length(lx, ly, cx, cy, ex, ey);
                }
                segments.push((PathSeg::QuadTo(cx, cy, ex, ey), cumulative));
                last = Some((ex, ey));
            }
            usvg::tiny_skia_path::PathSegment::Close => {
                segments.push((PathSeg::Close, cumulative));
                last = None;
            }
        }
    }

    (segments, cumulative)
}

fn apply_transform(x: f32, y: f32, t: usvg::Transform) -> (f32, f32) {
    let tx = t.sx * x + t.kx * y + t.tx;
    let ty = t.ky * x + t.sy * y + t.ty;
    (tx, ty)
}

/// Approximate cubic bezier arc length using recursive subdivision.
#[allow(clippy::too_many_arguments)]
fn cubic_arc_length(
    x0: f32,
    y0: f32,
    c1x: f32,
    c1y: f32,
    c2x: f32,
    c2y: f32,
    x3: f32,
    y3: f32,
) -> f32 {
    cubic_arc_length_recursive(x0, y0, c1x, c1y, c2x, c2y, x3, y3, 0)
}

#[allow(clippy::too_many_arguments)]
fn cubic_arc_length_recursive(
    x0: f32,
    y0: f32,
    c1x: f32,
    c1y: f32,
    c2x: f32,
    c2y: f32,
    x3: f32,
    y3: f32,
    depth: u32,
) -> f32 {
    // Chord length
    let dx = x3 - x0;
    let dy = y3 - y0;
    let chord = (dx * dx + dy * dy).sqrt();

    // Control polygon length
    let d1x = c1x - x0;
    let d1y = c1y - y0;
    let d2x = c2x - c1x;
    let d2y = c2y - c1y;
    let d3x = x3 - c2x;
    let d3y = y3 - c2y;
    let poly = (d1x * d1x + d1y * d1y).sqrt()
        + (d2x * d2x + d2y * d2y).sqrt()
        + (d3x * d3x + d3y * d3y).sqrt();

    if depth > 8 || (poly - chord).abs() < 0.01 {
        return (chord + poly) / 2.0;
    }

    // De Casteljau split at t=0.5
    let m01x = (x0 + c1x) / 2.0;
    let m01y = (y0 + c1y) / 2.0;
    let m12x = (c1x + c2x) / 2.0;
    let m12y = (c1y + c2y) / 2.0;
    let m23x = (c2x + x3) / 2.0;
    let m23y = (c2y + y3) / 2.0;
    let m012x = (m01x + m12x) / 2.0;
    let m012y = (m01y + m12y) / 2.0;
    let m123x = (m12x + m23x) / 2.0;
    let m123y = (m12y + m23y) / 2.0;
    let mx = (m012x + m123x) / 2.0;
    let my = (m012y + m123y) / 2.0;

    cubic_arc_length_recursive(x0, y0, m01x, m01y, m012x, m012y, mx, my, depth + 1)
        + cubic_arc_length_recursive(mx, my, m123x, m123y, m23x, m23y, x3, y3, depth + 1)
}

/// Approximate quadratic bezier arc length.
fn quad_arc_length(x0: f32, y0: f32, cx: f32, cy: f32, x2: f32, y2: f32) -> f32 {
    // Elevate to cubic
    let c1x = x0 + 2.0 / 3.0 * (cx - x0);
    let c1y = y0 + 2.0 / 3.0 * (cy - y0);
    let c2x = x2 + 2.0 / 3.0 * (cx - x2);
    let c2y = y2 + 2.0 / 3.0 * (cy - y2);
    cubic_arc_length(x0, y0, c1x, c1y, c2x, c2y, x2, y2)
}

/// Sample boundary points from path segments for chord-closure progress.
/// Returns a dense set of (x, y, progress) points along the path.
fn sample_boundary_points(segments: &[(PathSeg, f32)], total_length: f32) -> Vec<(f32, f32, f32)> {
    let progress = |cum: f32| -> f32 {
        if total_length > 0.0 {
            cum / total_length
        } else {
            0.0
        }
    };

    let mut points = Vec::new();
    let mut last: Option<(f32, f32)> = None;
    let samples_per_segment = 16;

    for (seg, cum) in segments {
        match seg {
            PathSeg::MoveTo(x, y) => {
                points.push((*x, *y, progress(*cum)));
                last = Some((*x, *y));
            }
            PathSeg::LineTo(x, y) => {
                if let Some((lx, ly)) = last {
                    let prev_cum = *cum - ((x - lx).powi(2) + (y - ly).powi(2)).sqrt();
                    for i in 1..=samples_per_segment {
                        let t = i as f32 / samples_per_segment as f32;
                        let px = lx + t * (x - lx);
                        let py = ly + t * (y - ly);
                        let p = progress(prev_cum + t * (*cum - prev_cum));
                        points.push((px, py, p));
                    }
                }
                last = Some((*x, *y));
            }
            PathSeg::CubicTo(c1x, c1y, c2x, c2y, ex, ey) => {
                if let Some((lx, ly)) = last {
                    let seg_len = cubic_arc_length(lx, ly, *c1x, *c1y, *c2x, *c2y, *ex, *ey);
                    let prev_cum = *cum - seg_len;
                    for i in 1..=samples_per_segment {
                        let t = i as f32 / samples_per_segment as f32;
                        let mt = 1.0 - t;
                        let px = mt.powi(3) * lx
                            + 3.0 * mt * mt * t * c1x
                            + 3.0 * mt * t * t * c2x
                            + t.powi(3) * ex;
                        let py = mt.powi(3) * ly
                            + 3.0 * mt * mt * t * c1y
                            + 3.0 * mt * t * t * c2y
                            + t.powi(3) * ey;
                        let p = progress(prev_cum + t * seg_len);
                        points.push((px, py, p));
                    }
                }
                last = Some((*ex, *ey));
            }
            PathSeg::QuadTo(cx, cy, ex, ey) => {
                if let Some((lx, ly)) = last {
                    let seg_len = quad_arc_length(lx, ly, *cx, *cy, *ex, *ey);
                    let prev_cum = *cum - seg_len;
                    for i in 1..=samples_per_segment {
                        let t = i as f32 / samples_per_segment as f32;
                        let mt = 1.0 - t;
                        let px = mt * mt * lx + 2.0 * mt * t * cx + t * t * ex;
                        let py = mt * mt * ly + 2.0 * mt * t * cy + t * t * ey;
                        let p = progress(prev_cum + t * seg_len);
                        points.push((px, py, p));
                    }
                }
                last = Some((*ex, *ey));
            }
            PathSeg::Close => {
                last = None;
            }
        }
    }

    points
}

/// Ray-casting point-in-polygon test for the partial polygon:
/// boundary[0], boundary[1], ..., boundary[k] with an implicit closing
/// edge from boundary[k] back to boundary[0].
fn point_in_partial_polygon(vx: f32, vy: f32, boundary: &[(f32, f32, f32)], k: usize) -> bool {
    let mut inside = false;
    let mut j = k;
    for i in 0..=k {
        let (xi, yi) = (boundary[i].0, boundary[i].1);
        let (xj, yj) = (boundary[j].0, boundary[j].1);
        if ((yi > vy) != (yj > vy)) && (vx < (xj - xi) * (vy - yi) / (yj - yi) + xi) {
            inside = !inside;
        }
        j = i;
    }
    inside
}

/// Compute the minimum progress α at which (vx, vy) is inside the
/// chord-closed partial path: arc[0→α] + chord(P(α)→P(0)).
/// This matches manim CE's `pointwise_become_partial` + fill behaviour
/// where the enclosed area grows as the path is progressively revealed.
fn chord_closure_progress(vx: f32, vy: f32, boundary: &[(f32, f32, f32)]) -> f32 {
    let n = boundary.len();
    if n < 3 {
        return 1.0;
    }
    for k in 2..n {
        if point_in_partial_polygon(vx, vy, boundary, k) {
            return boundary[k].2;
        }
    }
    1.0
}

/// Assign chord-closure progress to all fill vertices.
/// For each vertex, finds the minimum clip_threshold at which it would be
/// inside the polygon formed by the partial arc + closing chord. This
/// replaces the nearest-boundary-point algorithm to match manim CE's
/// partial-path fill behaviour.
fn assign_fill_chord_progress(vertices: &mut [[f32; 3]], boundary: &[(f32, f32, f32)]) {
    // Compute the maximum distance any vertex has from its nearest boundary
    // point. This lets us distinguish boundary vertices from interior ones.
    // Lyon sometimes tessellates shapes with only boundary vertices (e.g.
    // circles), in which case chord-closure ray casting is unreliable
    // because the test point sits exactly on a polygon edge.
    let mut max_boundary_dist = 0.0_f32;
    for v in vertices.iter() {
        let (vx, vy) = (v[0], v[1]);
        let mut best_d2 = f32::MAX;
        for &(bx, by, _) in boundary {
            let d2 = (vx - bx) * (vx - bx) + (vy - by) * (vy - by);
            if d2 < best_d2 {
                best_d2 = d2;
            }
        }
        let d = best_d2.sqrt();
        if d > max_boundary_dist {
            max_boundary_dist = d;
        }
    }

    // Threshold: vertices closer than 1% of max depth are "on the boundary".
    let boundary_eps = max_boundary_dist * 0.01;

    for v in vertices.iter_mut() {
        let (vx, vy) = (v[0], v[1]);

        // Find nearest boundary point and distance.
        let mut best_dist_sq = f32::MAX;
        let mut best_progress = v[2];
        for &(bx, by, bp) in boundary {
            let d2 = (vx - bx) * (vx - bx) + (vy - by) * (vy - by);
            if d2 < best_dist_sq {
                best_dist_sq = d2;
                best_progress = bp;
            }
        }

        if best_dist_sq.sqrt() <= boundary_eps {
            // Vertex is on/near the boundary: use arc-length progress.
            v[2] = best_progress;
        } else {
            // Interior vertex: use chord-closure progress.
            v[2] = chord_closure_progress(vx, vy, boundary);
        }
    }
}

/// Collect path segments with arc-length from flat command arrays.
fn collect_segments_from_commands(
    command_types: &[u8],
    command_data: &[f32],
) -> (Vec<(PathSeg, f32)>, f32) {
    let mut segments: Vec<(PathSeg, f32)> = Vec::new();
    let mut cumulative = 0.0f32;
    let mut last: Option<(f32, f32)> = None;
    let mut di = 0; // data index

    for &cmd in command_types {
        match cmd {
            0 => {
                // MoveTo(x, y)
                let x = command_data[di];
                let y = command_data[di + 1];
                di += 2;
                segments.push((PathSeg::MoveTo(x, y), cumulative));
                last = Some((x, y));
            }
            1 => {
                // LineTo(x, y)
                let x = command_data[di];
                let y = command_data[di + 1];
                di += 2;
                if let Some((lx, ly)) = last {
                    let dx = x - lx;
                    let dy = y - ly;
                    cumulative += (dx * dx + dy * dy).sqrt();
                }
                segments.push((PathSeg::LineTo(x, y), cumulative));
                last = Some((x, y));
            }
            2 => {
                // CubicTo(c1x, c1y, c2x, c2y, ex, ey)
                let c1x = command_data[di];
                let c1y = command_data[di + 1];
                let c2x = command_data[di + 2];
                let c2y = command_data[di + 3];
                let ex = command_data[di + 4];
                let ey = command_data[di + 5];
                di += 6;
                if let Some((lx, ly)) = last {
                    cumulative += cubic_arc_length(lx, ly, c1x, c1y, c2x, c2y, ex, ey);
                }
                segments.push((PathSeg::CubicTo(c1x, c1y, c2x, c2y, ex, ey), cumulative));
                last = Some((ex, ey));
            }
            3 => {
                // QuadTo(cx, cy, ex, ey)
                let cx = command_data[di];
                let cy = command_data[di + 1];
                let ex = command_data[di + 2];
                let ey = command_data[di + 3];
                di += 4;
                if let Some((lx, ly)) = last {
                    cumulative += quad_arc_length(lx, ly, cx, cy, ex, ey);
                }
                segments.push((PathSeg::QuadTo(cx, cy, ex, ey), cumulative));
                last = Some((ex, ey));
            }
            4 => {
                // Close
                segments.push((PathSeg::Close, cumulative));
                last = None;
            }
            _ => {}
        }
    }

    (segments, cumulative)
}

/// Tessellate path commands into separate fill and stroke geometries.
///
/// Handles tessellation resolution scaling, reference bounds, and auto-stroke
/// logic internally. Color/opacity are not passed here; they live on Material.
///
/// * `stroke_width` – when > 0, generate an explicit stroke. When 0,
///   a thin auto-stroke outline is generated. Negative suppresses all strokes.
#[pyfunction]
#[pyo3(signature = (command_types, command_data, *, fill_rule=None, stroke_width=0.0))]
pub fn tessellate(
    py: Python<'_>,
    command_types: Vec<u8>,
    command_data: Vec<f32>,
    fill_rule: Option<PyFillRule>,
    stroke_width: f32,
) -> PyResult<TessellationResult> {
    let color = [1.0, 1.0, 1.0, 1.0];

    // Decide auto-stroke: when no explicit stroke width is given.
    // Negative stroke_width explicitly suppresses all strokes (fill only).
    let auto_stroke = stroke_width == 0.0;

    let (segments, total_length) = collect_segments_from_commands(&command_types, &command_data);
    let (lyon_path, arc_length) = build_lyon_path_from_segments(&segments, total_length);

    let lr = if fill_rule.map_or(0, |r| r.value) == 1 {
        FillRule::EvenOdd
    } else {
        FillRule::NonZero
    };
    // Use tight tolerance for sub-pixel curve approximation at 1080p.
    let options = FillOptions::default()
        .with_fill_rule(lr)
        .with_tolerance(0.005);

    let mut fills: Vec<SubMesh> = Vec::new();
    let mut path_data: Vec<PathData> = Vec::new();

    // Tessellate fill
    let mut geometry: VertexBuffers<[f32; 3], u32> = VertexBuffers::new();
    let mut tessellator = FillTessellator::new();

    let result = tessellator.tessellate_path(
        &lyon_path,
        &options,
        &mut BuffersBuilder::new(&mut geometry, |mut vertex: FillVertex| {
            let pos = vertex.position();
            let progress = vertex.interpolated_attributes()[0];
            [pos.x, pos.y, progress]
        }),
    );

    if let Ok(()) = result
        && !geometry.indices.is_empty()
    {
        // Always populate path_data (needed for stroke generation)
        path_data.push(PathData {
            lyon_path,
            color,
            arc_length,
        });

        // Always create fill submesh (visibility controlled by Material.opacity)
        let boundary = sample_boundary_points(&segments, total_length);
        assign_fill_chord_progress(&mut geometry.vertices, &boundary);

        let num_verts = geometry.vertices.len();
        let positions: Vec<f32> = geometry
            .vertices
            .iter()
            .flat_map(|v| [v[0], v[1], 0.0])
            .collect();
        let normals: Vec<f32> = [0.0, 0.0, 1.0].repeat(num_verts);
        let progress: Vec<f32> = geometry.vertices.iter().map(|v| v[2]).collect();

        fills.push(SubMesh {
            positions,
            normals,
            progress,
            color,
            indices: geometry.indices,
            kind: 0,
            path_index: 0,
            colors: Vec::new(),
            use_lighting: 0.0,
        });
    }

    // Stroke generation
    let mut strokes: Vec<SubMesh> = Vec::new();
    if stroke_width > 0.0 {
        // Explicit stroke with user-specified width (color comes from Material)
        for (i, pd) in path_data.iter().enumerate() {
            if let Some(mut sm) = tessellate_stroke_miter(pd, stroke_width) {
                sm.color = color;
                sm.path_index = i as u32;
                strokes.push(sm);
            }
        }
    } else if auto_stroke {
        // Auto-stroke: thin outline proportional to bounding box height
        let bbox_height = if fills.is_empty() {
            1.0
        } else {
            let (_, min_y, _, _, max_y, _) = compute_bbox(&fills);
            let h = max_y - min_y;
            if h > 1e-9 { h } else { 1.0 }
        };
        let auto_sw = bbox_height * 0.008;

        for (i, pd) in path_data.iter().enumerate() {
            if let Some(mut stroke_sm) = tessellate_stroke(pd, auto_sw) {
                stroke_sm.path_index = i as u32;
                strokes.push(stroke_sm);
            }
        }
    }

    let arc_lengths: Vec<f32> = path_data.iter().map(|pd| pd.arc_length).collect();

    // Flip Y axis: PlanarPath uses math convention (Y-up at start angle -π/2),
    // negating Y makes shapes match Manim CE's visual orientation.
    fn flip_y(submeshes: &mut [SubMesh]) {
        for sm in submeshes.iter_mut() {
            for i in (1..sm.positions.len()).step_by(3) {
                sm.positions[i] = -sm.positions[i];
            }
        }
    }
    flip_y(&mut fills);
    flip_y(&mut strokes);

    // Compute bounds from all submeshes in path-space coordinates (post Y-flip)
    // without cloning.
    let bounds = {
        let bb = merge_bboxes(compute_bbox(&fills), compute_bbox(&strokes));
        if bb.0 != f32::MAX {
            bbox_to_bounds(bb)
        } else {
            [0.0; 6]
        }
    };

    let make_empty_geo = || Mesh {
        submeshes: Vec::new(),
        arc_lengths: Vec::new(),
        bounds,
        texture_positions: Vec::new(),
        texture_uvs: Vec::new(),
        texture_indices: Vec::new(),
    };

    let fill_geo = if fills.is_empty() {
        None
    } else {
        let mut geo = make_empty_geo();
        geo.submeshes = fills;
        geo.arc_lengths = arc_lengths.clone();
        Some(Py::new(py, geo)?)
    };

    let stroke_geo = if strokes.is_empty() {
        None
    } else {
        let mut geo = make_empty_geo();
        geo.submeshes = strokes;
        geo.arc_lengths = arc_lengths.clone();
        Some(Py::new(py, geo)?)
    };

    Ok(TessellationResult {
        fill_mesh: fill_geo,
        stroke_mesh: stroke_geo,
        arc_lengths,
    })
}

/// Center and scale submeshes using the given reference bounding box.
fn normalize_submeshes_with_ref(
    submeshes: &mut [SubMesh],
    ref_bbox: (f32, f32, f32, f32, f32, f32),
) {
    if submeshes.is_empty() {
        return;
    }

    let (min_x, min_y, min_z, max_x, max_y, max_z) = ref_bbox;
    let cx = (min_x + max_x) / 2.0;
    let cy = (min_y + max_y) / 2.0;
    let cz = (min_z + max_z) / 2.0;
    let height = max_y - min_y;
    let scale = if height > 1e-9 { 1.0 / height } else { 1.0 };

    // Center and scale, flip Y (SVG Y is down, manim Y is up)
    for sm in submeshes.iter_mut() {
        for i in (0..sm.positions.len()).step_by(3) {
            sm.positions[i] = (sm.positions[i] - cx) * scale;
            sm.positions[i + 1] = -(sm.positions[i + 1] - cy) * scale;
            sm.positions[i + 2] = (sm.positions[i + 2] - cz) * scale;
        }
    }
}

/// Center submeshes at origin and scale so the max extent = 1.0 (no Y flip).
fn normalize_submeshes_3d(submeshes: &mut [SubMesh]) {
    if submeshes.is_empty() {
        return;
    }

    let (min_x, min_y, min_z, max_x, max_y, max_z) = compute_bbox(submeshes);
    let cx = (min_x + max_x) / 2.0;
    let cy = (min_y + max_y) / 2.0;
    let cz = (min_z + max_z) / 2.0;
    let extent = (max_x - min_x).max(max_y - min_y).max(max_z - min_z);
    let scale = if extent > 1e-9 { 1.0 / extent } else { 1.0 };

    for sm in submeshes.iter_mut() {
        for i in (0..sm.positions.len()).step_by(3) {
            sm.positions[i] = (sm.positions[i] - cx) * scale;
            sm.positions[i + 1] = (sm.positions[i + 1] - cy) * scale;
            sm.positions[i + 2] = (sm.positions[i + 2] - cz) * scale;
        }
    }
}

/// Build a mesh from pre-computed 3D vertex data (positions, normals, indices).
#[pyfunction]
#[pyo3(signature = (positions, normals, indices, *, color=[255, 255, 255], opacity=1.0))]
pub fn build_surface(
    positions: Vec<f32>,
    normals: Vec<f32>,
    indices: Vec<u32>,
    color: [u8; 3],
    opacity: f32,
) -> PyResult<Mesh> {
    let num_verts = positions.len() / 3;
    let color = [
        color[0] as f32 / 255.0,
        color[1] as f32 / 255.0,
        color[2] as f32 / 255.0,
        opacity,
    ];

    let progress = vec![0.0; num_verts];

    let mut submeshes = vec![SubMesh {
        positions,
        normals,
        progress,
        color,
        indices,
        kind: 0,
        path_index: 0,
        colors: Vec::new(),
        use_lighting: 1.0,
    }];

    normalize_submeshes_3d(&mut submeshes);

    let bounds = if submeshes.is_empty() {
        [0.0; 6]
    } else {
        let (min_x, min_y, min_z, max_x, max_y, max_z) = compute_bbox(&submeshes);
        [min_x, min_y, min_z, max_x, max_y, max_z]
    };

    Ok(Mesh {
        submeshes,
        arc_lengths: Vec::new(),
        bounds,
        texture_positions: Vec::new(),
        texture_uvs: Vec::new(),
        texture_indices: Vec::new(),
    })
}

/// Build a textured quad mesh + texture from RGBA pixel data.
///
/// * `frames` – one or more RGBA blobs (one per animation frame).
/// * `width` / `height` – pixel dimensions (same for every frame).
///
/// Returns `(Mesh, Texture)`. The quad spans [-0.5, 0.5] in both X and Y
/// with Z = 0.  Actual world size is controlled via Object3D.scale.
#[pyfunction]
#[pyo3(signature = (frames, width, height))]
pub fn build_textured_quad(
    py: Python<'_>,
    frames: Vec<Vec<u8>>,
    width: u32,
    height: u32,
) -> PyResult<(Py<Mesh>, Py<Texture>)> {
    let expected = (width * height * 4) as usize;
    for (i, frame) in frames.iter().enumerate() {
        if frame.len() != expected {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "Frame {i} has {} bytes, expected {expected} ({}x{}x4)",
                frame.len(),
                width,
                height
            )));
        }
    }

    // Unit quad: 4 vertices, 6 indices
    #[rustfmt::skip]
    let texture_positions = vec![
        -0.5, -0.5, 0.0,
         0.5, -0.5, 0.0,
         0.5,  0.5, 0.0,
        -0.5,  0.5, 0.0,
    ];
    #[rustfmt::skip]
    let texture_uvs = vec![
        0.0, 0.0,
        1.0, 0.0,
        1.0, 1.0,
        0.0, 1.0,
    ];
    let texture_indices = vec![0, 1, 2, 0, 2, 3];

    let mesh = Py::new(
        py,
        Mesh {
            submeshes: Vec::new(),
            arc_lengths: Vec::new(),
            bounds: [-0.5, -0.5, 0.0, 0.5, 0.5, 0.0],
            texture_positions,
            texture_uvs,
            texture_indices,
        },
    )?;

    let texture = Py::new(
        py,
        Texture {
            frames,
            width,
            height,
        },
    )?;

    Ok((mesh, texture))
}
