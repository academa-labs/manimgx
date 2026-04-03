use crate::animation::keyframe::{AnimatedProperty, Keyframe, CAMERA_OBJECT_ID};
use crate::scene::Scene;

pub struct Timeline {
    pub keyframes: Vec<Keyframe>,
    pub cursor: f32,
}

impl Timeline {
    pub fn new() -> Self {
        Self {
            keyframes: Vec::new(),
            cursor: 0.0,
        }
    }

    pub fn add_keyframe(&mut self, keyframe: Keyframe) {
        self.keyframes.push(keyframe);
    }

    pub fn advance_cursor(&mut self, seconds: f32) {
        self.cursor += seconds;
    }

    pub fn total_duration(&self) -> f32 {
        let keyframe_end = self
            .keyframes
            .iter()
            .map(|kf| kf.start_time + kf.duration)
            .fold(0.0_f32, f32::max);
        keyframe_end.max(self.cursor)
    }

    /// Evaluate the scene at a specific time, applying all active animations.
    ///
    /// Sequential animations on the same property chain correctly:
    /// each keyframe lerps from the CURRENT value (which may already be
    /// modified by an earlier completed keyframe) to its target.
    pub fn evaluate(&self, scene: &mut Scene, time: f32) {
        // First reset everything to base state
        scene.reset_to_base();

        // Apply keyframes in order — each lerps from current value, not base.
        // This lets sequential animations chain: if keyframe A moved pos to X
        // and keyframe B moves pos to Y, B lerps from X (not from base).
        for kf in &self.keyframes {
            // Skip keyframes that haven't started yet
            if time < kf.start_time {
                continue;
            }

            // Completed or zero-duration keyframes snap to target (skip easing math)
            let end_time = kf.start_time + kf.duration;
            let eased_t = if kf.duration <= 0.0 || time >= end_time {
                1.0
            } else {
                let local_t = (time - kf.start_time) / kf.duration;
                kf.easing.evaluate(local_t)
            };

            // Camera keyframes use the sentinel ID
            if kf.object_id == CAMERA_OBJECT_ID {
                match &kf.property {
                    AnimatedProperty::CameraPosition(target) => {
                        let current = scene.camera.camera.position;
                        scene.camera.camera.position = current + ((*target - current) * eased_t);
                    }
                    AnimatedProperty::CameraLookAt(target) => {
                        let current = scene.camera.camera.look_at;
                        scene.camera.camera.look_at = current + ((*target - current) * eased_t);
                    }
                    _ => {} // Other properties don't apply to camera
                }
                continue;
            }

            // ObjectId == Vec index (objects are never removed, IDs are sequential)
            if let Some(obj) = scene.objects.get_mut(kf.object_id) {
                match &kf.property {
                    AnimatedProperty::Translation(target) => {
                        let current = obj.transform.translation;
                        obj.transform.translation = current + ((*target - current) * eased_t);
                    }
                    AnimatedProperty::Rotation(target) => {
                        let current = obj.transform.rotation;
                        obj.transform.rotation = current + ((*target - current) * eased_t);
                    }
                    AnimatedProperty::Scale(target) => {
                        let current = obj.transform.scale;
                        obj.transform.scale = current + ((*target - current) * eased_t);
                    }
                    AnimatedProperty::Color(target) => {
                        // RGB only — don't touch color[3] (alpha is controlled by opacity)
                        let cr = obj.material.color[0];
                        let cg = obj.material.color[1];
                        let cb = obj.material.color[2];
                        obj.material.color[0] = cr + (target.x - cr) * eased_t;
                        obj.material.color[1] = cg + (target.y - cg) * eased_t;
                        obj.material.color[2] = cb + (target.z - cb) * eased_t;
                    }
                    AnimatedProperty::Opacity(target) => {
                        let current = obj.material.opacity;
                        obj.material.opacity = current + (target - current) * eased_t;
                    }
                    _ => {} // Camera properties handled above
                }
            }
        }
    }
}

impl Default for Timeline {
    fn default() -> Self {
        Self::new()
    }
}
