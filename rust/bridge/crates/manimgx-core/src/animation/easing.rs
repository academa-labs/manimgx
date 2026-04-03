use std::f32::consts::PI;

#[derive(Clone, Copy, Debug)]
pub enum EasingFunction {
    Linear,
    EaseIn,
    EaseOut,
    EaseInOut,
    EaseInQuad,
    EaseOutQuad,
    EaseInOutQuad,
    EaseInCubic,
    EaseOutCubic,
    EaseInOutCubic,
}

impl EasingFunction {
    pub fn parse(s: &str) -> Self {
        match s {
            "linear" => Self::Linear,
            "ease_in" => Self::EaseIn,
            "ease_out" => Self::EaseOut,
            "ease_in_out" => Self::EaseInOut,
            "ease_in_quad" => Self::EaseInQuad,
            "ease_out_quad" => Self::EaseOutQuad,
            "ease_in_out_quad" => Self::EaseInOutQuad,
            "ease_in_cubic" => Self::EaseInCubic,
            "ease_out_cubic" => Self::EaseOutCubic,
            "ease_in_out_cubic" => Self::EaseInOutCubic,
            _ => Self::Linear,
        }
    }

    pub fn evaluate(&self, t: f32) -> f32 {
        let t = t.clamp(0.0, 1.0);
        match self {
            Self::Linear => t,
            Self::EaseIn => 1.0 - ((t * PI / 2.0).cos()),
            Self::EaseOut => (t * PI / 2.0).sin(),
            Self::EaseInOut => -(((t * PI).cos() - 1.0) / 2.0),
            Self::EaseInQuad => t * t,
            Self::EaseOutQuad => 1.0 - (1.0 - t) * (1.0 - t),
            Self::EaseInOutQuad => {
                if t < 0.5 {
                    2.0 * t * t
                } else {
                    1.0 - (-2.0 * t + 2.0).powi(2) / 2.0
                }
            }
            Self::EaseInCubic => t * t * t,
            Self::EaseOutCubic => 1.0 - (1.0 - t).powi(3),
            Self::EaseInOutCubic => {
                if t < 0.5 {
                    4.0 * t * t * t
                } else {
                    1.0 - (-2.0 * t + 2.0).powi(3) / 2.0
                }
            }
        }
    }
}
