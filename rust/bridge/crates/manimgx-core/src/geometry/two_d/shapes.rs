use crate::vertex::Vertex;
use std::f32::consts::PI;

pub struct Circle;
pub struct Rectangle;
pub struct Line;
pub struct Arc;
pub struct Arrow;
pub struct Dot;
pub struct CurvedArrow;
pub struct DashedLine;
pub struct Brace;
pub struct FilledRegion;
pub struct RiemannRects;

const NORMAL_2D: [f32; 3] = [0.0, 0.0, 1.0];

impl Circle {
    /// Generate a filled circle with optional stroke.
    pub fn generate(
        radius: f32,
        fill_color: [f32; 4],
        stroke_color: [f32; 4],
        stroke_width: f32,
        segments: u32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        // Circle is just a high-segment regular polygon
        super::polygon::RegularPolygon::generate(
            segments,
            radius,
            fill_color,
            stroke_color,
            stroke_width,
        )
    }
}

impl Rectangle {
    /// Generate a filled rectangle centered at origin in XY plane.
    pub fn generate(
        width: f32,
        height: f32,
        fill_color: [f32; 4],
        stroke_color: [f32; 4],
        stroke_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let hw = width / 2.0;
        let hh = height / 2.0;
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        // Fill: two triangles
        vertices.push(Vertex::new([-hw, -hh, 0.0], NORMAL_2D, fill_color));
        vertices.push(Vertex::new([hw, -hh, 0.0], NORMAL_2D, fill_color));
        vertices.push(Vertex::new([hw, hh, 0.0], NORMAL_2D, fill_color));
        vertices.push(Vertex::new([-hw, hh, 0.0], NORMAL_2D, fill_color));
        indices.extend_from_slice(&[0, 1, 2, 0, 2, 3]);

        // Stroke: quad strip around perimeter
        if stroke_width > 0.0 {
            let half_w = stroke_width / 2.0;
            let corners: [[f32; 2]; 4] = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];

            let stroke_base = vertices.len() as u32;

            for i in 0..4u32 {
                let curr = corners[i as usize];
                let next = corners[((i + 1) % 4) as usize];

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

            for i in 0..4u32 {
                let base = stroke_base + i * 2;
                let next_base = stroke_base + ((i + 1) % 4) * 2;
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

impl Line {
    /// Generate a line (quad) between two XY points.
    pub fn generate(
        start: [f32; 2],
        end: [f32; 2],
        color: [f32; 4],
        width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let dx = end[0] - start[0];
        let dy = end[1] - start[1];
        let len = (dx * dx + dy * dy).sqrt().max(1e-6);
        let nx = -dy / len * width / 2.0;
        let ny = dx / len * width / 2.0;

        let vertices = vec![
            Vertex::new([start[0] - nx, start[1] - ny, 0.0], NORMAL_2D, color),
            Vertex::new([start[0] + nx, start[1] + ny, 0.0], NORMAL_2D, color),
            Vertex::new([end[0] + nx, end[1] + ny, 0.0], NORMAL_2D, color),
            Vertex::new([end[0] - nx, end[1] - ny, 0.0], NORMAL_2D, color),
        ];
        let indices = vec![0, 1, 2, 0, 2, 3];

        (vertices, indices)
    }
}

impl Arc {
    /// Generate an arc (partial circle outline) as a quad strip.
    pub fn generate(
        radius: f32,
        start_angle: f32,
        end_angle: f32,
        color: [f32; 4],
        width: f32,
        segments: u32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        let half_w = width / 2.0;

        let angle_span = end_angle - start_angle;

        for i in 0..=segments {
            let t = i as f32 / segments as f32;
            let angle = start_angle + t * angle_span;
            let cos_a = angle.cos();
            let sin_a = angle.sin();

            // Inner and outer points
            let inner_r = radius - half_w;
            let outer_r = radius + half_w;

            vertices.push(Vertex::new(
                [cos_a * inner_r, sin_a * inner_r, 0.0],
                NORMAL_2D,
                color,
            ));
            vertices.push(Vertex::new(
                [cos_a * outer_r, sin_a * outer_r, 0.0],
                NORMAL_2D,
                color,
            ));
        }

        for i in 0..segments {
            let base = i * 2;
            indices.push(base);
            indices.push(base + 1);
            indices.push(base + 2);

            indices.push(base + 2);
            indices.push(base + 1);
            indices.push(base + 3);
        }

        (vertices, indices)
    }
}

impl Arrow {
    /// Generate an arrow from start to end with a triangular head.
    pub fn generate(
        start: [f32; 2],
        end: [f32; 2],
        color: [f32; 4],
        width: f32,
        head_length: f32,
        head_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let dx = end[0] - start[0];
        let dy = end[1] - start[1];
        let len = (dx * dx + dy * dy).sqrt().max(1e-6);
        let ux = dx / len;
        let uy = dy / len;

        // The shaft ends where the arrowhead begins
        let shaft_end = [end[0] - ux * head_length, end[1] - uy * head_length];

        // Shaft (line quad)
        let nx = -uy * width / 2.0;
        let ny = ux * width / 2.0;

        let mut vertices = vec![
            Vertex::new([start[0] - nx, start[1] - ny, 0.0], NORMAL_2D, color),
            Vertex::new([start[0] + nx, start[1] + ny, 0.0], NORMAL_2D, color),
            Vertex::new(
                [shaft_end[0] + nx, shaft_end[1] + ny, 0.0],
                NORMAL_2D,
                color,
            ),
            Vertex::new(
                [shaft_end[0] - nx, shaft_end[1] - ny, 0.0],
                NORMAL_2D,
                color,
            ),
        ];
        let mut indices = vec![0, 1, 2, 0, 2, 3];

        // Arrowhead (triangle)
        let head_nx = -uy * head_width / 2.0;
        let head_ny = ux * head_width / 2.0;

        let head_base = vertices.len() as u32;
        vertices.push(Vertex::new(
            [shaft_end[0] - head_nx, shaft_end[1] - head_ny, 0.0],
            NORMAL_2D,
            color,
        ));
        vertices.push(Vertex::new(
            [shaft_end[0] + head_nx, shaft_end[1] + head_ny, 0.0],
            NORMAL_2D,
            color,
        ));
        vertices.push(Vertex::new([end[0], end[1], 0.0], NORMAL_2D, color));

        indices.push(head_base);
        indices.push(head_base + 1);
        indices.push(head_base + 2);

        (vertices, indices)
    }
}

impl Dot {
    /// Generate a small filled circle (dot) at a position.
    pub fn generate(
        position: [f32; 2],
        radius: f32,
        color: [f32; 4],
        segments: u32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        // Center vertex
        let center_idx = 0u32;
        vertices.push(Vertex::new(
            [position[0], position[1], 0.0],
            NORMAL_2D,
            color,
        ));

        // Perimeter vertices
        for i in 0..segments {
            let angle = (i as f32) * 2.0 * PI / segments as f32;
            vertices.push(Vertex::new(
                [
                    position[0] + angle.cos() * radius,
                    position[1] + angle.sin() * radius,
                    0.0,
                ],
                NORMAL_2D,
                color,
            ));
        }

        for i in 0..segments {
            indices.push(center_idx);
            indices.push(1 + i);
            indices.push(1 + (i + 1) % segments);
        }

        (vertices, indices)
    }
}

impl CurvedArrow {
    /// Generate an arc with an arrowhead at the end.
    pub fn generate(
        radius: f32,
        start_angle: f32,
        end_angle: f32,
        color: [f32; 4],
        width: f32,
        head_length: f32,
        head_width: f32,
        segments: u32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        let half_w = width / 2.0;

        // Shorten the arc to make room for the arrowhead
        let angle_span = end_angle - start_angle;
        let head_angle = head_length / radius;
        let arc_end = end_angle - head_angle;

        // Arc body (quad strip)
        let arc_span = arc_end - start_angle;
        for i in 0..=segments {
            let t = i as f32 / segments as f32;
            let angle = start_angle + t * arc_span;
            let cos_a = angle.cos();
            let sin_a = angle.sin();

            let inner_r = radius - half_w;
            let outer_r = radius + half_w;

            vertices.push(Vertex::new(
                [cos_a * inner_r, sin_a * inner_r, 0.0],
                NORMAL_2D,
                color,
            ));
            vertices.push(Vertex::new(
                [cos_a * outer_r, sin_a * outer_r, 0.0],
                NORMAL_2D,
                color,
            ));
        }

        for i in 0..segments {
            let base = i * 2;
            indices.push(base);
            indices.push(base + 1);
            indices.push(base + 2);
            indices.push(base + 2);
            indices.push(base + 1);
            indices.push(base + 3);
        }

        // Arrowhead triangle at arc_end
        let head_base_idx = vertices.len() as u32;
        let cos_end = arc_end.cos();
        let sin_end = arc_end.sin();

        // Tangent direction at arc_end (perpendicular to radius, in the direction of angle increase)
        let sign = if angle_span >= 0.0 { 1.0 } else { -1.0 };
        let tx = -sin_end * sign;
        let ty = cos_end * sign;

        // Normal to arc at this point (radial direction)
        let nx = cos_end;
        let ny = sin_end;

        // Head base points (perpendicular to tangent)
        let half_hw = head_width / 2.0;
        let base_x = cos_end * radius;
        let base_y = sin_end * radius;

        vertices.push(Vertex::new(
            [base_x - nx * half_hw, base_y - ny * half_hw, 0.0],
            NORMAL_2D,
            color,
        ));
        vertices.push(Vertex::new(
            [base_x + nx * half_hw, base_y + ny * half_hw, 0.0],
            NORMAL_2D,
            color,
        ));

        // Tip point
        let tip_x = base_x + tx * head_length;
        let tip_y = base_y + ty * head_length;
        vertices.push(Vertex::new([tip_x, tip_y, 0.0], NORMAL_2D, color));

        indices.push(head_base_idx);
        indices.push(head_base_idx + 1);
        indices.push(head_base_idx + 2);

        (vertices, indices)
    }
}

impl DashedLine {
    /// Generate a dashed line between two points.
    pub fn generate(
        start: [f32; 2],
        end: [f32; 2],
        color: [f32; 4],
        width: f32,
        dash_length: f32,
        gap_length: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let dx = end[0] - start[0];
        let dy = end[1] - start[1];
        let total_len = (dx * dx + dy * dy).sqrt().max(1e-6);
        let ux = dx / total_len;
        let uy = dy / total_len;
        let nx = -uy * width / 2.0;
        let ny = ux * width / 2.0;

        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        let pattern_len = dash_length + gap_length;
        let mut dist = 0.0;

        while dist < total_len {
            let d_end = (dist + dash_length).min(total_len);
            let sx = start[0] + ux * dist;
            let sy = start[1] + uy * dist;
            let ex = start[0] + ux * d_end;
            let ey = start[1] + uy * d_end;

            let base = vertices.len() as u32;
            vertices.push(Vertex::new([sx - nx, sy - ny, 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([sx + nx, sy + ny, 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([ex + nx, ey + ny, 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([ex - nx, ey - ny, 0.0], NORMAL_2D, color));

            indices.push(base);
            indices.push(base + 1);
            indices.push(base + 2);
            indices.push(base);
            indices.push(base + 2);
            indices.push(base + 3);

            dist += pattern_len;
        }

        (vertices, indices)
    }
}

impl Brace {
    /// Generate a curly brace shape in 2D. The brace spans from `start` to `end`
    /// with the curl pointing in the direction of the normal.
    pub fn generate(
        start: [f32; 2],
        end: [f32; 2],
        color: [f32; 4],
        width: f32,
        curl_size: f32,
        segments: u32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let dx = end[0] - start[0];
        let dy = end[1] - start[1];
        let len = (dx * dx + dy * dy).sqrt().max(1e-6);
        let ux = dx / len;
        let uy = dy / len;
        // Normal pointing outward (perpendicular)
        let nx = -uy;
        let ny = ux;

        // Build the brace as a series of quad segments following a parametric path
        // The brace has 4 arcs: start curl, first half, second half, end curl
        let total_segs = segments.max(16);
        let mut path_points = Vec::with_capacity(total_segs as usize + 1);

        for i in 0..=total_segs {
            let t = i as f32 / total_segs as f32;

            // Parametric brace: smooth curve from start to end with curl at middle
            let along = start[0] + dx * t;
            let along_y = start[1] + dy * t;

            // Curl function: peaks at t=0.5, zero at t=0 and t=1
            // Use sin^2 for smooth bump, with a sharper peak at the midpoint
            let curl = if t < 0.5 {
                let s = t * 2.0;
                curl_size * (s * PI).sin()
            } else {
                let s = (t - 0.5) * 2.0;
                curl_size * ((1.0 - s) * PI).sin()
            };

            // Add small hooks at the tips
            let hook = if t < 0.05 {
                curl_size * 0.3 * ((t / 0.05) * PI * 0.5).sin()
            } else if t > 0.95 {
                curl_size * 0.3 * (((1.0 - t) / 0.05) * PI * 0.5).sin()
            } else {
                0.0
            };

            let px = along + nx * (curl + hook);
            let py = along_y + ny * (curl + hook);
            path_points.push([px, py]);
        }

        // Convert path to quad strip
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        let half_w = width / 2.0;

        for i in 0..path_points.len() {
            let p = path_points[i];

            // Compute tangent direction
            let tangent = if i == 0 {
                let next = path_points[1];
                [next[0] - p[0], next[1] - p[1]]
            } else if i == path_points.len() - 1 {
                let prev = path_points[i - 1];
                [p[0] - prev[0], p[1] - prev[1]]
            } else {
                let prev = path_points[i - 1];
                let next = path_points[i + 1];
                [next[0] - prev[0], next[1] - prev[1]]
            };

            let tlen = (tangent[0] * tangent[0] + tangent[1] * tangent[1])
                .sqrt()
                .max(1e-6);
            let tnx = -tangent[1] / tlen * half_w;
            let tny = tangent[0] / tlen * half_w;

            vertices.push(Vertex::new(
                [p[0] - tnx, p[1] - tny, 0.0],
                NORMAL_2D,
                color,
            ));
            vertices.push(Vertex::new(
                [p[0] + tnx, p[1] + tny, 0.0],
                NORMAL_2D,
                color,
            ));
        }

        for i in 0..(path_points.len() as u32 - 1) {
            let base = i * 2;
            indices.push(base);
            indices.push(base + 1);
            indices.push(base + 2);
            indices.push(base + 2);
            indices.push(base + 1);
            indices.push(base + 3);
        }

        // Add the midpoint tip triangle
        let mid_idx = total_segs / 2;
        let mid_point = path_points[mid_idx as usize];
        let tip_base = vertices.len() as u32;
        let tip_offset = curl_size * 0.4;
        vertices.push(Vertex::new(
            [mid_point[0] + nx * tip_offset - ux * width, mid_point[1] + ny * tip_offset - uy * width, 0.0],
            NORMAL_2D,
            color,
        ));
        vertices.push(Vertex::new(
            [mid_point[0] + nx * tip_offset + ux * width, mid_point[1] + ny * tip_offset + uy * width, 0.0],
            NORMAL_2D,
            color,
        ));
        vertices.push(Vertex::new(
            [mid_point[0] + nx * (tip_offset + curl_size * 0.3), mid_point[1] + ny * (tip_offset + curl_size * 0.3), 0.0],
            NORMAL_2D,
            color,
        ));
        indices.push(tip_base);
        indices.push(tip_base + 1);
        indices.push(tip_base + 2);

        (vertices, indices)
    }
}

impl FilledRegion {
    /// Generate a filled region between a curve (given as points) and the x-axis (y=baseline).
    pub fn generate(
        points: &[[f32; 2]],
        baseline: f32,
        color: [f32; 4],
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        if points.len() < 2 {
            return (vertices, indices);
        }

        // For each point, create a vertex pair: one at the curve, one at the baseline
        for &p in points {
            vertices.push(Vertex::new([p[0], p[1], 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([p[0], baseline, 0.0], NORMAL_2D, color));
        }

        // Create quads between adjacent point pairs
        for i in 0..(points.len() as u32 - 1) {
            let base = i * 2;
            // Triangle 1: curve[i], baseline[i], curve[i+1]
            indices.push(base);
            indices.push(base + 1);
            indices.push(base + 2);
            // Triangle 2: curve[i+1], baseline[i], baseline[i+1]
            indices.push(base + 2);
            indices.push(base + 1);
            indices.push(base + 3);
        }

        (vertices, indices)
    }
}

impl RiemannRects {
    /// Generate Riemann sum rectangles for a function sampled at points.
    /// Each rectangle spans from baseline to y_value at the sampled x position.
    pub fn generate(
        x_positions: &[f32],
        y_values: &[f32],
        dx: f32,
        baseline: f32,
        fill_color: [f32; 4],
        stroke_color: [f32; 4],
        stroke_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        let half_dx = dx / 2.0;

        for (&x, &y) in x_positions.iter().zip(y_values.iter()) {
            let base = vertices.len() as u32;

            // Rectangle fill (2 triangles)
            let left = x - half_dx;
            let right = x + half_dx;
            let bot = baseline;
            let top = y;

            vertices.push(Vertex::new([left, bot, 0.0], NORMAL_2D, fill_color));
            vertices.push(Vertex::new([right, bot, 0.0], NORMAL_2D, fill_color));
            vertices.push(Vertex::new([right, top, 0.0], NORMAL_2D, fill_color));
            vertices.push(Vertex::new([left, top, 0.0], NORMAL_2D, fill_color));

            indices.push(base);
            indices.push(base + 1);
            indices.push(base + 2);
            indices.push(base);
            indices.push(base + 2);
            indices.push(base + 3);

            // Stroke outline
            if stroke_width > 0.0 {
                let hw = stroke_width / 2.0;
                let corners: [[f32; 2]; 4] = [
                    [left, bot],
                    [right, bot],
                    [right, top],
                    [left, top],
                ];

                for edge in 0..4u32 {
                    let curr = corners[edge as usize];
                    let next = corners[((edge + 1) % 4) as usize];

                    let edx = next[0] - curr[0];
                    let edy = next[1] - curr[1];
                    let elen = (edx * edx + edy * edy).sqrt().max(1e-6);
                    let enx = -edy / elen * hw;
                    let eny = edx / elen * hw;

                    let sb = vertices.len() as u32;
                    vertices.push(Vertex::new(
                        [curr[0] - enx, curr[1] - eny, 0.0],
                        NORMAL_2D,
                        stroke_color,
                    ));
                    vertices.push(Vertex::new(
                        [curr[0] + enx, curr[1] + eny, 0.0],
                        NORMAL_2D,
                        stroke_color,
                    ));
                    vertices.push(Vertex::new(
                        [next[0] + enx, next[1] + eny, 0.0],
                        NORMAL_2D,
                        stroke_color,
                    ));
                    vertices.push(Vertex::new(
                        [next[0] - enx, next[1] - eny, 0.0],
                        NORMAL_2D,
                        stroke_color,
                    ));

                    indices.push(sb);
                    indices.push(sb + 1);
                    indices.push(sb + 2);
                    indices.push(sb);
                    indices.push(sb + 2);
                    indices.push(sb + 3);
                }
            }
        }

        (vertices, indices)
    }
}
