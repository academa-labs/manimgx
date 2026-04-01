use crate::vertex::Vertex;
use std::f32::consts::PI;

pub struct Cube;
pub struct Box3D;
pub struct Sphere;
pub struct Cylinder;
pub struct Plane;
pub struct ParametricSurface;

impl Cube {
    pub fn generate(size: f32, color: [f32; 4]) -> (Vec<Vertex>, Vec<u32>) {
        let h = size / 2.0;

        #[rustfmt::skip]
        let face_data: &[([f32; 3], [[f32; 3]; 4])] = &[
            // normal, 4 corner positions
            ([0.0, 0.0, 1.0],  [[-h, -h, h], [h, -h, h], [h, h, h], [-h, h, h]]),   // front
            ([0.0, 0.0, -1.0], [[h, -h, -h], [-h, -h, -h], [-h, h, -h], [h, h, -h]]), // back
            ([0.0, 1.0, 0.0],  [[-h, h, h], [h, h, h], [h, h, -h], [-h, h, -h]]),    // top
            ([0.0, -1.0, 0.0], [[-h, -h, -h], [h, -h, -h], [h, -h, h], [-h, -h, h]]), // bottom
            ([1.0, 0.0, 0.0],  [[h, -h, h], [h, -h, -h], [h, h, -h], [h, h, h]]),    // right
            ([-1.0, 0.0, 0.0], [[-h, -h, -h], [-h, -h, h], [-h, h, h], [-h, h, -h]]), // left
        ];

        let mut vertices = Vec::with_capacity(24);
        let mut indices = Vec::with_capacity(36);

        for (normal, positions) in face_data {
            let base = vertices.len() as u32;
            for pos in positions {
                vertices.push(Vertex::new(*pos, *normal, color));
            }
            indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
        }

        (vertices, indices)
    }
}

impl Box3D {
    /// Generate a rectangular prism (box) with independent width, height, depth.
    /// Width = X axis, Height = Y axis, Depth = Z axis.
    pub fn generate(width: f32, height: f32, depth: f32, color: [f32; 4]) -> (Vec<Vertex>, Vec<u32>) {
        let hw = width / 2.0;
        let hh = height / 2.0;
        let hd = depth / 2.0;

        #[rustfmt::skip]
        let face_data: &[([f32; 3], [[f32; 3]; 4])] = &[
            ([0.0, 0.0, 1.0],  [[-hw, -hh, hd], [hw, -hh, hd], [hw, hh, hd], [-hw, hh, hd]]),    // front
            ([0.0, 0.0, -1.0], [[hw, -hh, -hd], [-hw, -hh, -hd], [-hw, hh, -hd], [hw, hh, -hd]]), // back
            ([0.0, 1.0, 0.0],  [[-hw, hh, hd], [hw, hh, hd], [hw, hh, -hd], [-hw, hh, -hd]]),    // top
            ([0.0, -1.0, 0.0], [[-hw, -hh, -hd], [hw, -hh, -hd], [hw, -hh, hd], [-hw, -hh, hd]]), // bottom
            ([1.0, 0.0, 0.0],  [[hw, -hh, hd], [hw, -hh, -hd], [hw, hh, -hd], [hw, hh, hd]]),    // right
            ([-1.0, 0.0, 0.0], [[-hw, -hh, -hd], [-hw, -hh, hd], [-hw, hh, hd], [-hw, hh, -hd]]), // left
        ];

        let mut vertices = Vec::with_capacity(24);
        let mut indices = Vec::with_capacity(36);

        for (normal, positions) in face_data {
            let base = vertices.len() as u32;
            for pos in positions {
                vertices.push(Vertex::new(*pos, *normal, color));
            }
            indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
        }

        (vertices, indices)
    }
}

impl Sphere {
    pub fn generate(
        radius: f32,
        color: [f32; 4],
        segments: u32,
        rings: u32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        for ring in 0..=rings {
            let theta = ring as f32 * PI / rings as f32;
            let sin_theta = theta.sin();
            let cos_theta = theta.cos();

            for seg in 0..=segments {
                let phi = seg as f32 * 2.0 * PI / segments as f32;
                let sin_phi = phi.sin();
                let cos_phi = phi.cos();

                let x = sin_theta * cos_phi;
                let y = cos_theta;
                let z = sin_theta * sin_phi;

                vertices.push(Vertex::new(
                    [x * radius, y * radius, z * radius],
                    [x, y, z],
                    color,
                ));
            }
        }

        for ring in 0..rings {
            for seg in 0..segments {
                let current = ring * (segments + 1) + seg;
                let next = current + segments + 1;

                indices.extend_from_slice(&[current, next, current + 1]);
                indices.extend_from_slice(&[current + 1, next, next + 1]);
            }
        }

        (vertices, indices)
    }
}

impl Cylinder {
    pub fn generate(
        radius: f32,
        height: f32,
        color: [f32; 4],
        segments: u32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        let half_h = height / 2.0;

        // Side vertices
        for i in 0..=segments {
            let angle = i as f32 * 2.0 * PI / segments as f32;
            let x = angle.cos() * radius;
            let z = angle.sin() * radius;
            let nx = angle.cos();
            let nz = angle.sin();

            vertices.push(Vertex::new([x, -half_h, z], [nx, 0.0, nz], color));
            vertices.push(Vertex::new([x, half_h, z], [nx, 0.0, nz], color));
        }

        // Side indices
        for i in 0..segments {
            let base = i * 2;
            indices.extend_from_slice(&[base, base + 1, base + 2]);
            indices.extend_from_slice(&[base + 2, base + 1, base + 3]);
        }

        // Top cap
        let top_center = vertices.len() as u32;
        vertices.push(Vertex::new([0.0, half_h, 0.0], [0.0, 1.0, 0.0], color));
        for i in 0..=segments {
            let angle = i as f32 * 2.0 * PI / segments as f32;
            let x = angle.cos() * radius;
            let z = angle.sin() * radius;
            vertices.push(Vertex::new([x, half_h, z], [0.0, 1.0, 0.0], color));
        }
        for i in 0..segments {
            indices.extend_from_slice(&[top_center, top_center + 1 + i, top_center + 2 + i]);
        }

        // Bottom cap
        let bot_center = vertices.len() as u32;
        vertices.push(Vertex::new([0.0, -half_h, 0.0], [0.0, -1.0, 0.0], color));
        for i in 0..=segments {
            let angle = i as f32 * 2.0 * PI / segments as f32;
            let x = angle.cos() * radius;
            let z = angle.sin() * radius;
            vertices.push(Vertex::new([x, -half_h, z], [0.0, -1.0, 0.0], color));
        }
        for i in 0..segments {
            indices.extend_from_slice(&[bot_center, bot_center + 2 + i, bot_center + 1 + i]);
        }

        (vertices, indices)
    }
}

impl Plane {
    pub fn generate(width: f32, depth: f32, color: [f32; 4]) -> (Vec<Vertex>, Vec<u32>) {
        let hw = width / 2.0;
        let hd = depth / 2.0;
        let up = [0.0, 1.0, 0.0];

        let vertices = vec![
            Vertex::new([-hw, 0.0, -hd], up, color),
            Vertex::new([hw, 0.0, -hd], up, color),
            Vertex::new([hw, 0.0, hd], up, color),
            Vertex::new([-hw, 0.0, hd], up, color),
        ];
        let indices = vec![0, 2, 1, 0, 3, 2];

        (vertices, indices)
    }
}

impl ParametricSurface {
    /// Generate a parametric surface from pre-computed point grid.
    /// `points` is a row-major grid of [x, y, z] positions, with dimensions `u_steps × v_steps`.
    /// Normals are computed from cross products of partial derivatives.
    pub fn generate(
        points: &[[f32; 3]],
        u_steps: u32,
        v_steps: u32,
        color: [f32; 4],
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::with_capacity((u_steps * v_steps) as usize);
        let mut indices = Vec::new();

        // Build vertices with computed normals
        for vi in 0..v_steps {
            for ui in 0..u_steps {
                let idx = (vi * u_steps + ui) as usize;
                let p = points[idx];

                // Compute normal via finite differences
                let du = if ui + 1 < u_steps {
                    let next = points[idx + 1];
                    [next[0] - p[0], next[1] - p[1], next[2] - p[2]]
                } else if ui > 0 {
                    let prev = points[idx - 1];
                    [p[0] - prev[0], p[1] - prev[1], p[2] - prev[2]]
                } else {
                    [1.0, 0.0, 0.0]
                };

                let dv = if vi + 1 < v_steps {
                    let next = points[(idx + u_steps as usize).min(points.len() - 1)];
                    [next[0] - p[0], next[1] - p[1], next[2] - p[2]]
                } else if vi > 0 {
                    let prev = points[idx.saturating_sub(u_steps as usize)];
                    [p[0] - prev[0], p[1] - prev[1], p[2] - prev[2]]
                } else {
                    [0.0, 0.0, 1.0]
                };

                // Cross product du × dv
                let normal = [
                    du[1] * dv[2] - du[2] * dv[1],
                    du[2] * dv[0] - du[0] * dv[2],
                    du[0] * dv[1] - du[1] * dv[0],
                ];
                let len = (normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2])
                    .sqrt()
                    .max(1e-6);
                let normal = [normal[0] / len, normal[1] / len, normal[2] / len];

                vertices.push(Vertex::new(p, normal, color));
            }
        }

        // Build triangle indices
        for vi in 0..(v_steps - 1) {
            for ui in 0..(u_steps - 1) {
                let tl = vi * u_steps + ui;
                let tr = tl + 1;
                let bl = tl + u_steps;
                let br = bl + 1;

                indices.push(tl);
                indices.push(bl);
                indices.push(tr);

                indices.push(tr);
                indices.push(bl);
                indices.push(br);
            }
        }

        (vertices, indices)
    }
}
