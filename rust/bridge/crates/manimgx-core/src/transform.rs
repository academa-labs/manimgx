use glam::{Mat4, Quat, Vec3};

#[derive(Clone, Copy, Debug)]
pub struct Transform {
    pub translation: Vec3,
    pub rotation: Vec3,
    pub scale: Vec3,
}

impl Default for Transform {
    fn default() -> Self {
        Self {
            translation: Vec3::ZERO,
            rotation: Vec3::ZERO,
            scale: Vec3::ONE,
        }
    }
}

impl Transform {
    pub fn to_matrix(&self) -> Mat4 {
        // Fast path: skip quaternion for zero rotation (common for 2D objects)
        if self.rotation == Vec3::ZERO {
            return Mat4::from_scale_rotation_translation(
                self.scale,
                Quat::IDENTITY,
                self.translation,
            );
        }
        let rotation_quat = Quat::from_euler(
            glam::EulerRot::YXZ,
            self.rotation.y.to_radians(),
            self.rotation.x.to_radians(),
            self.rotation.z.to_radians(),
        );
        Mat4::from_scale_rotation_translation(self.scale, rotation_quat, self.translation)
    }

    pub fn lerp(&self, other: &Transform, t: f32) -> Transform {
        Transform {
            translation: self.translation.lerp(other.translation, t),
            rotation: self.rotation.lerp(other.rotation, t),
            scale: self.scale.lerp(other.scale, t),
        }
    }
}
