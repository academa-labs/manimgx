use crate::scene::Scene;

/// Trait for timeline evaluation — allows renderer to drive frame evaluation
/// without depending on manimgx-core's Timeline directly.
pub trait TimelineEval {
    fn evaluate(&self, scene: &mut Scene, time: f32);
}

/// Adapter: wraps manimgx_core::animation::timeline::Timeline
impl TimelineEval for crate::animation::timeline::Timeline {
    fn evaluate(&self, scene: &mut Scene, time: f32) {
        self.evaluate(scene, time);
    }
}
