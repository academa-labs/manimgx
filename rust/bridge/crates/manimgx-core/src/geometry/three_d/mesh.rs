use crate::vertex::Vertex;

pub struct SurfaceMesh;

impl SurfaceMesh {
    /// Generate a mesh from a function f(x, z) -> y
    /// over the domain [x_min, x_max] x [z_min, z_max]
    pub fn from_function<F>(
        f: F,
        x_range: [f32; 2],
        z_range: [f32; 2],
        resolution: u32,
        color: [f32; 4],
    ) -> (Vec<Vertex>, Vec<u32>)
    where
        F: Fn(f32, f32) -> f32,
    {
        let n_verts = ((resolution + 1) * (resolution + 1)) as usize;
        let n_indices = (resolution * resolution * 6) as usize;
        let mut vertices = Vec::with_capacity(n_verts);
        let mut indices = Vec::with_capacity(n_indices);

        let dx = (x_range[1] - x_range[0]) / resolution as f32;
        let dz = (z_range[1] - z_range[0]) / resolution as f32;

        for zi in 0..=resolution {
            for xi in 0..=resolution {
                let x = x_range[0] + xi as f32 * dx;
                let z = z_range[0] + zi as f32 * dz;
                let y = f(x, z);

                // Approximate normal via central differences
                let eps = 0.001;
                let dydx = (f(x + eps, z) - f(x - eps, z)) / (2.0 * eps);
                let dydz = (f(x, z + eps) - f(x, z - eps)) / (2.0 * eps);
                let normal = [-dydx, 1.0, -dydz];
                let len =
                    (normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]).sqrt();
                let normal = [normal[0] / len, normal[1] / len, normal[2] / len];

                vertices.push(Vertex::new([x, y, z], normal, color));
            }
        }

        for zi in 0..resolution {
            for xi in 0..resolution {
                let current = zi * (resolution + 1) + xi;
                let next_row = current + resolution + 1;
                indices.extend_from_slice(&[current, next_row, current + 1]);
                indices.extend_from_slice(&[current + 1, next_row, next_row + 1]);
            }
        }

        (vertices, indices)
    }
}
