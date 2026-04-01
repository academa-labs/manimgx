use crate::vertex::Vertex;
use glam::Vec3;

pub struct BezierCurve;

impl BezierCurve {
    /// De Casteljau evaluation of a cubic Bezier at parameter t
    fn evaluate(points: &[Vec3; 4], t: f32) -> Vec3 {
        let p01 = points[0].lerp(points[1], t);
        let p12 = points[1].lerp(points[2], t);
        let p23 = points[2].lerp(points[3], t);
        let p012 = p01.lerp(p12, t);
        let p123 = p12.lerp(p23, t);
        p012.lerp(p123, t)
    }

    /// Tangent of a cubic Bezier at parameter t
    fn tangent(points: &[Vec3; 4], t: f32) -> Vec3 {
        let p01 = points[0].lerp(points[1], t);
        let p12 = points[1].lerp(points[2], t);
        let p23 = points[2].lerp(points[3], t);
        let p012 = p01.lerp(p12, t);
        let p123 = p12.lerp(p23, t);
        (p123 - p012).normalize_or_zero()
    }

    /// Tessellate a cubic Bezier into a tube mesh
    pub fn generate_tube(
        control_points: &[[f32; 3]; 4],
        color: [f32; 4],
        width: f32,
        segments: u32,
        radial_segments: u32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let points = [
            Vec3::from_array(control_points[0]),
            Vec3::from_array(control_points[1]),
            Vec3::from_array(control_points[2]),
            Vec3::from_array(control_points[3]),
        ];

        let radius = width / 2.0;
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        for i in 0..=segments {
            let t = i as f32 / segments as f32;
            let center = Self::evaluate(&points, t);
            let forward = Self::tangent(&points, t);

            // Build a frame around the curve
            let up = if forward.dot(Vec3::Y).abs() > 0.99 {
                Vec3::Z
            } else {
                Vec3::Y
            };
            let right = forward.cross(up).normalize();
            let actual_up = right.cross(forward).normalize();

            for j in 0..=radial_segments {
                let angle = j as f32 * 2.0 * std::f32::consts::PI / radial_segments as f32;
                let normal = right * angle.cos() + actual_up * angle.sin();
                let pos = center + normal * radius;
                vertices.push(Vertex::new(pos.to_array(), normal.to_array(), color));
            }
        }

        for i in 0..segments {
            for j in 0..radial_segments {
                let current = i * (radial_segments + 1) + j;
                let next = current + radial_segments + 1;
                indices.extend_from_slice(&[current, next, current + 1]);
                indices.extend_from_slice(&[current + 1, next, next + 1]);
            }
        }

        (vertices, indices)
    }

}
