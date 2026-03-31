use crate::vertex::Vertex;

pub struct FunctionPlot;

const NORMAL_2D: [f32; 3] = [0.0, 0.0, 1.0];

impl FunctionPlot {
    /// Generate a line strip as a quad strip from pre-sampled [x, y] points.
    pub fn from_points(
        points: &[[f32; 2]],
        color: [f32; 4],
        width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        if points.len() < 2 {
            return (vertices, indices);
        }

        let half_w = width / 2.0;

        for i in 0..points.len() {
            // Compute tangent direction for this point
            let tangent = if i == 0 {
                let dx = points[1][0] - points[0][0];
                let dy = points[1][1] - points[0][1];
                [dx, dy]
            } else if i == points.len() - 1 {
                let dx = points[i][0] - points[i - 1][0];
                let dy = points[i][1] - points[i - 1][1];
                [dx, dy]
            } else {
                let dx = points[i + 1][0] - points[i - 1][0];
                let dy = points[i + 1][1] - points[i - 1][1];
                [dx, dy]
            };

            let len = (tangent[0] * tangent[0] + tangent[1] * tangent[1])
                .sqrt()
                .max(1e-6);
            // Normal perpendicular to tangent
            let nx = -tangent[1] / len * half_w;
            let ny = tangent[0] / len * half_w;

            let p = points[i];
            vertices.push(Vertex::new([p[0] - nx, p[1] - ny, 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([p[0] + nx, p[1] + ny, 0.0], NORMAL_2D, color));
        }

        for i in 0..(points.len() - 1) as u32 {
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
