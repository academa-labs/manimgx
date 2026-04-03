use crate::animation::easing::EasingFunction;
use crate::scene::ObjectId;
use glam::Vec3;

/// Sentinel object ID used for camera keyframes (not associated with any scene object).
pub const CAMERA_OBJECT_ID: ObjectId = usize::MAX;

#[derive(Clone, Copy, Debug)]
pub enum AnimatedProperty {
    Translation(Vec3),
    Rotation(Vec3),
    Scale(Vec3),
    Color(Vec3),
    Opacity(f32),
    CameraPosition(Vec3),
    CameraLookAt(Vec3),
}

#[derive(Clone, Copy, Debug)]
pub struct Keyframe {
    pub object_id: ObjectId,
    pub property: AnimatedProperty,
    pub start_time: f32,
    pub duration: f32,
    pub easing: EasingFunction,
}
