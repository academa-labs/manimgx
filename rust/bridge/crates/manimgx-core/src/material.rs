#[derive(Clone, Copy, Debug)]
pub struct Material {
    pub color: [f32; 4],
    pub fill_color: [f32; 4],
    pub stroke_color: [f32; 4],
    pub stroke_width: f32,
    pub fill_opacity: f32,
    pub opacity: f32,
    pub use_vertex_colors: bool,
}

impl Default for Material {
    fn default() -> Self {
        Self {
            color: [1.0, 1.0, 1.0, 1.0],
            fill_color: [1.0, 1.0, 1.0, 1.0],
            stroke_color: [1.0, 1.0, 1.0, 1.0],
            stroke_width: 0.0,
            fill_opacity: 1.0,
            opacity: 1.0,
            use_vertex_colors: false,
        }
    }
}

impl Material {
    pub fn new(r: f32, g: f32, b: f32) -> Self {
        Self {
            color: [r, g, b, 1.0],
            fill_color: [r, g, b, 1.0],
            stroke_color: [r, g, b, 1.0],
            stroke_width: 0.0,
            fill_opacity: 1.0,
            opacity: 1.0,
            use_vertex_colors: false,
        }
    }

    pub fn with_alpha(r: f32, g: f32, b: f32, a: f32) -> Self {
        Self {
            color: [r, g, b, a],
            fill_color: [r, g, b, a],
            stroke_color: [r, g, b, a],
            stroke_width: 0.0,
            fill_opacity: a,
            opacity: 1.0,
            use_vertex_colors: false,
        }
    }

    pub fn for_2d_shape(
        fill_color: [f32; 4],
        stroke_color: [f32; 4],
        stroke_width: f32,
        fill_opacity: f32,
    ) -> Self {
        Self {
            color: fill_color,
            fill_color,
            stroke_color,
            stroke_width,
            fill_opacity,
            opacity: 1.0,
            use_vertex_colors: true,
        }
    }

    pub fn lerp(&self, other: &Material, t: f32) -> Material {
        Material {
            color: [
                self.color[0] + (other.color[0] - self.color[0]) * t,
                self.color[1] + (other.color[1] - self.color[1]) * t,
                self.color[2] + (other.color[2] - self.color[2]) * t,
                self.color[3] + (other.color[3] - self.color[3]) * t,
            ],
            fill_color: [
                self.fill_color[0] + (other.fill_color[0] - self.fill_color[0]) * t,
                self.fill_color[1] + (other.fill_color[1] - self.fill_color[1]) * t,
                self.fill_color[2] + (other.fill_color[2] - self.fill_color[2]) * t,
                self.fill_color[3] + (other.fill_color[3] - self.fill_color[3]) * t,
            ],
            stroke_color: [
                self.stroke_color[0] + (other.stroke_color[0] - self.stroke_color[0]) * t,
                self.stroke_color[1] + (other.stroke_color[1] - self.stroke_color[1]) * t,
                self.stroke_color[2] + (other.stroke_color[2] - self.stroke_color[2]) * t,
                self.stroke_color[3] + (other.stroke_color[3] - self.stroke_color[3]) * t,
            ],
            stroke_width: self.stroke_width + (other.stroke_width - self.stroke_width) * t,
            fill_opacity: self.fill_opacity + (other.fill_opacity - self.fill_opacity) * t,
            opacity: self.opacity + (other.opacity - self.opacity) * t,
            use_vertex_colors: other.use_vertex_colors,
        }
    }
}
