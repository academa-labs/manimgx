use crate::vertex::Vertex;
use std::f32::consts::PI;

pub struct RegularPolygon;
pub struct Polygram;
pub struct Triangle;

const NORMAL_2D: [f32; 3] = [0.0, 0.0, 1.0];

impl RegularPolygon {
    /// Generate a regular polygon with `sides` sides, centered at origin in the XY plane.
    /// Fill is a triangle fan, stroke is a quad strip around the perimeter.
    pub fn generate(
        sides: u32,
        radius: f32,
        fill_color: [f32; 4],
        stroke_color: [f32; 4],
        stroke_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        // Compute corner positions
        let corners: Vec<[f32; 2]> = (0..sides)
            .map(|i| {
                let angle = (i as f32) * 2.0 * PI / sides as f32 - PI / 2.0;
                [angle.cos() * radius, angle.sin() * radius]
            })
            .collect();

        // Fill: triangle fan from center
        let center_idx = vertices.len() as u32;
        vertices.push(Vertex::new([0.0, 0.0, 0.0], NORMAL_2D, fill_color));

        for corner in &corners {
            vertices.push(Vertex::new(
                [corner[0], corner[1], 0.0],
                NORMAL_2D,
                fill_color,
            ));
        }

        for i in 0..sides {
            indices.push(center_idx);
            indices.push(center_idx + 1 + i);
            indices.push(center_idx + 1 + (i + 1) % sides);
        }

        // Stroke: quad strip around perimeter
        if stroke_width > 0.0 {
            let half_w = stroke_width / 2.0;
            let stroke_base = vertices.len() as u32;

            for i in 0..sides {
                let curr = corners[i as usize];
                let next = corners[((i + 1) % sides) as usize];

                // Direction along edge
                let dx = next[0] - curr[0];
                let dy = next[1] - curr[1];
                let len = (dx * dx + dy * dy).sqrt();
                // Outward normal (perpendicular)
                let nx = -dy / len;
                let ny = dx / len;

                // Inner and outer vertices for this corner
                let inner = [curr[0] - nx * half_w, curr[1] - ny * half_w];
                let outer = [curr[0] + nx * half_w, curr[1] + ny * half_w];

                vertices.push(Vertex::new(
                    [inner[0], inner[1], 0.0],
                    NORMAL_2D,
                    stroke_color,
                ));
                vertices.push(Vertex::new(
                    [outer[0], outer[1], 0.0],
                    NORMAL_2D,
                    stroke_color,
                ));
            }

            for i in 0..sides {
                let base = stroke_base + i * 2;
                let next_base = stroke_base + ((i + 1) % sides) * 2;
                // Two triangles forming a quad between this edge and next
                indices.push(base);
                indices.push(base + 1);
                indices.push(next_base);

                indices.push(next_base);
                indices.push(base + 1);
                indices.push(next_base + 1);
            }
        }

        (vertices, indices)
    }
}

impl Polygram {
    /// Generate a star polygon {points/step}.
    /// `points` = number of outer vertices, `step` = connect every `step`-th vertex.
    pub fn generate(
        points: u32,
        step: u32,
        outer_radius: f32,
        fill_color: [f32; 4],
        stroke_color: [f32; 4],
        stroke_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        // Compute inner radius using the star polygon formula
        let inner_radius =
            outer_radius * (PI / points as f32).cos() / (PI * step as f32 / points as f32).cos();

        // Generate alternating outer/inner vertices
        let total = points * 2;
        let star_pts: Vec<[f32; 2]> = (0..total)
            .map(|i| {
                let angle = (i as f32) * PI / points as f32 - PI / 2.0;
                let r = if i % 2 == 0 {
                    outer_radius
                } else {
                    inner_radius
                };
                [angle.cos() * r, angle.sin() * r]
            })
            .collect();

        // Fill: triangle fan from center
        let center_idx = vertices.len() as u32;
        vertices.push(Vertex::new([0.0, 0.0, 0.0], NORMAL_2D, fill_color));

        for pt in &star_pts {
            vertices.push(Vertex::new([pt[0], pt[1], 0.0], NORMAL_2D, fill_color));
        }

        for i in 0..total {
            indices.push(center_idx);
            indices.push(center_idx + 1 + i);
            indices.push(center_idx + 1 + (i + 1) % total);
        }

        // Stroke: quad strip around perimeter
        if stroke_width > 0.0 {
            let half_w = stroke_width / 2.0;
            let stroke_base = vertices.len() as u32;

            for i in 0..total {
                let curr = star_pts[i as usize];
                let next = star_pts[((i + 1) % total) as usize];

                let dx = next[0] - curr[0];
                let dy = next[1] - curr[1];
                let len = (dx * dx + dy * dy).sqrt().max(1e-6);
                let nx = -dy / len;
                let ny = dx / len;

                let inner = [curr[0] - nx * half_w, curr[1] - ny * half_w];
                let outer = [curr[0] + nx * half_w, curr[1] + ny * half_w];

                vertices.push(Vertex::new(
                    [inner[0], inner[1], 0.0],
                    NORMAL_2D,
                    stroke_color,
                ));
                vertices.push(Vertex::new(
                    [outer[0], outer[1], 0.0],
                    NORMAL_2D,
                    stroke_color,
                ));
            }

            for i in 0..total {
                let base = stroke_base + i * 2;
                let next_base = stroke_base + ((i + 1) % total) * 2;
                indices.push(base);
                indices.push(base + 1);
                indices.push(next_base);

                indices.push(next_base);
                indices.push(base + 1);
                indices.push(next_base + 1);
            }
        }

        (vertices, indices)
    }
}

impl Triangle {
    /// Generate an equilateral triangle with circumradius `radius`.
    pub fn equilateral(
        radius: f32,
        fill_color: [f32; 4],
        stroke_color: [f32; 4],
        stroke_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        RegularPolygon::generate(3, radius, fill_color, stroke_color, stroke_width)
    }

    /// Generate a triangle from three arbitrary XY vertices.
    pub fn from_vertices(
        v0: [f32; 2],
        v1: [f32; 2],
        v2: [f32; 2],
        fill_color: [f32; 4],
        stroke_color: [f32; 4],
        stroke_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        let corners = [v0, v1, v2];

        // Fill: single triangle
        for c in &corners {
            vertices.push(Vertex::new([c[0], c[1], 0.0], NORMAL_2D, fill_color));
        }
        indices.extend_from_slice(&[0, 1, 2]);

        // Stroke: quad strip around perimeter
        if stroke_width > 0.0 {
            let half_w = stroke_width / 2.0;
            let stroke_base = vertices.len() as u32;

            for i in 0..3u32 {
                let curr = corners[i as usize];
                let next = corners[((i + 1) % 3) as usize];

                let dx = next[0] - curr[0];
                let dy = next[1] - curr[1];
                let len = (dx * dx + dy * dy).sqrt().max(1e-6);
                let nx = -dy / len;
                let ny = dx / len;

                let inner = [curr[0] - nx * half_w, curr[1] - ny * half_w];
                let outer = [curr[0] + nx * half_w, curr[1] + ny * half_w];

                vertices.push(Vertex::new(
                    [inner[0], inner[1], 0.0],
                    NORMAL_2D,
                    stroke_color,
                ));
                vertices.push(Vertex::new(
                    [outer[0], outer[1], 0.0],
                    NORMAL_2D,
                    stroke_color,
                ));
            }

            for i in 0..3u32 {
                let base = stroke_base + i * 2;
                let next_base = stroke_base + ((i + 1) % 3) * 2;
                indices.push(base);
                indices.push(base + 1);
                indices.push(next_base);

                indices.push(next_base);
                indices.push(base + 1);
                indices.push(next_base + 1);
            }
        }

        (vertices, indices)
    }
}
