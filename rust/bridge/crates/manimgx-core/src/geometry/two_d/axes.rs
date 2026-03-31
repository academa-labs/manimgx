use crate::vertex::Vertex;

pub struct NumberLine;
pub struct Axes2D;
pub struct Grid;

const NORMAL_2D: [f32; 3] = [0.0, 0.0, 1.0];

impl NumberLine {
    /// Generate a horizontal number line with tick marks.
    /// `range` = [min, max], line along x-axis at y=0.
    pub fn generate(
        range: [f32; 2],
        color: [f32; 4],
        line_width: f32,
        tick_spacing: f32,
        tick_height: f32,
        tick_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        // Main horizontal line
        let half_w = line_width / 2.0;
        let base = vertices.len() as u32;
        vertices.push(Vertex::new([range[0], -half_w, 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([range[0], half_w, 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([range[1], half_w, 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([range[1], -half_w, 0.0], NORMAL_2D, color));
        indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);

        // Tick marks
        if tick_spacing > 0.0 {
            let half_th = tick_height / 2.0;
            let half_tw = tick_width / 2.0;

            // Start from the first tick position >= range[0]
            let start_tick = (range[0] / tick_spacing).ceil() as i32;
            let end_tick = (range[1] / tick_spacing).floor() as i32;

            for i in start_tick..=end_tick {
                let x = i as f32 * tick_spacing;
                let base = vertices.len() as u32;
                vertices.push(Vertex::new([x - half_tw, -half_th, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([x + half_tw, -half_th, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([x + half_tw, half_th, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([x - half_tw, half_th, 0.0], NORMAL_2D, color));
                indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
            }
        }

        (vertices, indices)
    }
}

impl Axes2D {
    /// Generate X and Y axes with optional arrow tips.
    #[allow(clippy::too_many_arguments)]
    pub fn generate(
        x_range: [f32; 2],
        y_range: [f32; 2],
        color: [f32; 4],
        line_width: f32,
        tick_spacing: f32,
        tick_height: f32,
        tick_width: f32,
        include_arrows: bool,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();

        // X-axis: horizontal line
        let half_w = line_width / 2.0;
        let base = vertices.len() as u32;
        vertices.push(Vertex::new([x_range[0], -half_w, 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([x_range[0], half_w, 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([x_range[1], half_w, 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([x_range[1], -half_w, 0.0], NORMAL_2D, color));
        indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);

        // Y-axis: vertical line
        let base = vertices.len() as u32;
        vertices.push(Vertex::new([-half_w, y_range[0], 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([half_w, y_range[0], 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([half_w, y_range[1], 0.0], NORMAL_2D, color));
        vertices.push(Vertex::new([-half_w, y_range[1], 0.0], NORMAL_2D, color));
        indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);

        // X-axis tick marks
        if tick_spacing > 0.0 {
            let half_th = tick_height / 2.0;
            let half_tw = tick_width / 2.0;

            let start = (x_range[0] / tick_spacing).ceil() as i32;
            let end = (x_range[1] / tick_spacing).floor() as i32;
            for i in start..=end {
                if i == 0 {
                    continue;
                } // skip origin
                let x = i as f32 * tick_spacing;
                let base = vertices.len() as u32;
                vertices.push(Vertex::new([x - half_tw, -half_th, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([x + half_tw, -half_th, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([x + half_tw, half_th, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([x - half_tw, half_th, 0.0], NORMAL_2D, color));
                indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
            }

            // Y-axis tick marks
            let start = (y_range[0] / tick_spacing).ceil() as i32;
            let end = (y_range[1] / tick_spacing).floor() as i32;
            for i in start..=end {
                if i == 0 {
                    continue;
                }
                let y = i as f32 * tick_spacing;
                let base = vertices.len() as u32;
                vertices.push(Vertex::new([-half_th, y - half_tw, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([half_th, y - half_tw, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([half_th, y + half_tw, 0.0], NORMAL_2D, color));
                vertices.push(Vertex::new([-half_th, y + half_tw, 0.0], NORMAL_2D, color));
                indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
            }
        }

        // Arrow tips
        if include_arrows {
            let arrow_len = tick_height * 1.5;
            let arrow_half_w = tick_height * 0.8;

            // X-axis arrow (pointing right)
            let base = vertices.len() as u32;
            vertices.push(Vertex::new(
                [x_range[1], -arrow_half_w, 0.0],
                NORMAL_2D,
                color,
            ));
            vertices.push(Vertex::new(
                [x_range[1], arrow_half_w, 0.0],
                NORMAL_2D,
                color,
            ));
            vertices.push(Vertex::new(
                [x_range[1] + arrow_len, 0.0, 0.0],
                NORMAL_2D,
                color,
            ));
            indices.extend_from_slice(&[base, base + 1, base + 2]);

            // Y-axis arrow (pointing up)
            let base = vertices.len() as u32;
            vertices.push(Vertex::new(
                [-arrow_half_w, y_range[1], 0.0],
                NORMAL_2D,
                color,
            ));
            vertices.push(Vertex::new(
                [arrow_half_w, y_range[1], 0.0],
                NORMAL_2D,
                color,
            ));
            vertices.push(Vertex::new(
                [0.0, y_range[1] + arrow_len, 0.0],
                NORMAL_2D,
                color,
            ));
            indices.extend_from_slice(&[base, base + 1, base + 2]);
        }

        (vertices, indices)
    }
}

impl Grid {
    /// Generate a background grid of lines in the XY plane.
    pub fn generate(
        x_range: [f32; 2],
        y_range: [f32; 2],
        spacing: f32,
        color: [f32; 4],
        line_width: f32,
    ) -> (Vec<Vertex>, Vec<u32>) {
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        let half_w = line_width / 2.0;

        // Vertical lines
        let start_x = (x_range[0] / spacing).ceil() as i32;
        let end_x = (x_range[1] / spacing).floor() as i32;
        for i in start_x..=end_x {
            let x = i as f32 * spacing;
            let base = vertices.len() as u32;
            vertices.push(Vertex::new([x - half_w, y_range[0], 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([x + half_w, y_range[0], 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([x + half_w, y_range[1], 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([x - half_w, y_range[1], 0.0], NORMAL_2D, color));
            indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
        }

        // Horizontal lines
        let start_y = (y_range[0] / spacing).ceil() as i32;
        let end_y = (y_range[1] / spacing).floor() as i32;
        for i in start_y..=end_y {
            let y = i as f32 * spacing;
            let base = vertices.len() as u32;
            vertices.push(Vertex::new([x_range[0], y - half_w, 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([x_range[1], y - half_w, 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([x_range[1], y + half_w, 0.0], NORMAL_2D, color));
            vertices.push(Vertex::new([x_range[0], y + half_w, 0.0], NORMAL_2D, color));
            indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
        }

        (vertices, indices)
    }
}
