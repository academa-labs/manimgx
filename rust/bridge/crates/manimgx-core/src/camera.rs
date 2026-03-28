use glam::{Mat4, Vec3};

/// View transform — position, look_at, up. Shared by all projection types.
#[derive(Clone, Copy, Debug)]
pub struct Camera {
    pub position: Vec3,
    pub look_at: Vec3,
    pub up: Vec3,
}

impl Default for Camera {
    fn default() -> Self {
        Self {
            position: Vec3::new(3.0, 2.0, 5.0),
            look_at: Vec3::ZERO,
            up: Vec3::Y,
        }
    }
}

impl Camera {
    pub fn view_matrix(&self) -> Mat4 {
        Mat4::look_at_rh(self.position, self.look_at, self.up)
    }
}

/// Projection type — each variant stores its own parameters and computes its own matrix.
#[derive(Clone, Copy, Debug)]
pub enum Projection {
    /// Standard perspective projection.
    Perspective { fov: f32, near: f32, far: f32 },
    /// Parallel projection with oblique rays (cabinet/cavalier).
    /// `alpha` — angle of oblique rays in degrees.
    /// `l` — foreshortening ratio (0.5 = cabinet, 1.0 = cavalier).
    /// `height` — visible vertical range in world units. Width = height * aspect_ratio.
    Oblique {
        alpha: f32,
        l: f32,
        height: f32,
        near: f32,
        far: f32,
    },
}

impl Projection {
    /// Returns the pure projection matrix (no oblique shear).
    pub fn projection_matrix(&self, _aspect_ratio: f32) -> Mat4 {
        match self {
            Projection::Perspective { fov, near, far } => {
                Mat4::perspective_rh(fov.to_radians(), _aspect_ratio, *near, *far)
            }
            Projection::Oblique {
                height, near, far, ..
            } => {
                let width = height * _aspect_ratio;
                let half_w = width / 2.0;
                let half_h = height / 2.0;
                Mat4::orthographic_rh(-half_w, half_w, -half_h, half_h, *near, *far)
            }
        }
    }

    /// Returns the oblique shear matrix (identity for non-oblique projections).
    /// This shear must be applied in world space (before the view transform)
    /// so that objects at z=0 are unaffected.
    pub fn world_shear_matrix(&self) -> Mat4 {
        match self {
            Projection::Perspective { .. } => Mat4::IDENTITY,
            Projection::Oblique { alpha, l, .. } => {
                let alpha_rad = alpha.to_radians();
                let shear_x = l * alpha_rad.cos();
                let shear_y = l * alpha_rad.sin();
                Mat4::from_cols_array(&[
                    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, shear_x, shear_y, 1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0,
                ])
            }
        }
    }
}

impl Default for Projection {
    fn default() -> Self {
        Projection::Perspective {
            fov: 45.0,
            near: 0.1,
            far: 100.0,
        }
    }
}

/// Composes Camera (view) + Projection into a single rig.
/// Stored in Scene, consumed by renderer.
#[derive(Clone, Copy, Debug, Default)]
pub struct CameraRig {
    pub camera: Camera,
    pub projection: Projection,
}

impl CameraRig {
    pub fn view_projection_matrix(&self, aspect_ratio: f32) -> Mat4 {
        // Oblique shear is applied in world space (before view transform)
        // so that 2D objects at z=0 are unaffected by the shear.
        // Pipeline: projection * view * shear * world_pos
        let proj = self.projection.projection_matrix(aspect_ratio);
        let view = self.camera.view_matrix();
        let shear = self.projection.world_shear_matrix();
        proj * view * shear
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn camera_view_matrix_look_at() {
        let camera = Camera {
            position: Vec3::new(0.0, 0.0, 5.0),
            look_at: Vec3::ZERO,
            up: Vec3::Y,
        };
        let view = camera.view_matrix();
        let expected = Mat4::look_at_rh(Vec3::new(0.0, 0.0, 5.0), Vec3::ZERO, Vec3::Y);
        assert_eq!(view, expected);
    }

    #[test]
    fn perspective_projection_matches_glam() {
        let proj = Projection::Perspective {
            fov: 45.0,
            near: 0.1,
            far: 100.0,
        };
        let aspect = 16.0 / 9.0;
        let mat = proj.projection_matrix(aspect);
        let expected = Mat4::perspective_rh(45.0_f32.to_radians(), aspect, 0.1, 100.0);
        assert_eq!(mat, expected);
    }

    #[test]
    fn oblique_cavalier_vs_cabinet() {
        let cavalier = Projection::Oblique {
            alpha: 45.0,
            l: 1.0,
            height: 10.0,
            near: 0.1,
            far: 100.0,
        };
        let cabinet = Projection::Oblique {
            alpha: 45.0,
            l: 0.5,
            height: 10.0,
            near: 0.1,
            far: 100.0,
        };

        // Cavalier has stronger shear than cabinet (l=1.0 vs l=0.5)
        let cav_shear = cavalier.world_shear_matrix();
        let cab_shear = cabinet.world_shear_matrix();
        assert_ne!(cav_shear, Mat4::IDENTITY);
        assert_ne!(cab_shear, Mat4::IDENTITY);
        assert_ne!(cav_shear, cab_shear);
    }

    #[test]
    fn oblique_different_angles() {
        let alpha0 = Projection::Oblique {
            alpha: 0.0,
            l: 0.5,
            height: 10.0,
            near: 0.1,
            far: 100.0,
        };
        let alpha45 = Projection::Oblique {
            alpha: 45.0,
            l: 0.5,
            height: 10.0,
            near: 0.1,
            far: 100.0,
        };
        let shear0 = alpha0.world_shear_matrix();
        let shear45 = alpha45.world_shear_matrix();
        assert_ne!(shear0, shear45);
    }

    #[test]
    fn oblique_2d_objects_unaffected_by_shear() {
        // Objects at z=0 should not be displaced by oblique shear
        let proj = Projection::Oblique {
            alpha: 45.0,
            l: 0.5,
            height: 8.0,
            near: 0.1,
            far: 100.0,
        };
        let shear = proj.world_shear_matrix();
        let point_at_z0 = glam::Vec4::new(3.0, 2.0, 0.0, 1.0);
        let result = shear * point_at_z0;
        assert_eq!(result.x, 3.0);
        assert_eq!(result.y, 2.0);
        assert_eq!(result.z, 0.0);
    }

    #[test]
    fn camera_rig_perspective_view_projection() {
        // For perspective (no shear), view_projection = projection * view
        let rig = CameraRig {
            camera: Camera {
                position: Vec3::new(3.0, 2.0, 5.0),
                look_at: Vec3::ZERO,
                up: Vec3::Y,
            },
            projection: Projection::Perspective {
                fov: 60.0,
                near: 0.5,
                far: 200.0,
            },
        };
        let aspect = 16.0 / 9.0;
        let vp = rig.view_projection_matrix(aspect);
        let expected = rig.projection.projection_matrix(aspect) * rig.camera.view_matrix();
        assert_eq!(vp, expected);
    }
}
