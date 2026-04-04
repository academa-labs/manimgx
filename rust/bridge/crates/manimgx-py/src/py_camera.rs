use manimgx_core::camera::{Camera, CameraRig, Projection};
use glam::Vec3;
use pyo3::prelude::*;

#[pyclass(name = "PerspectiveCamera", from_py_object)]
#[derive(Clone)]
pub struct PyPerspectiveCamera {
    pub inner: CameraRig,
}

#[pymethods]
impl PyPerspectiveCamera {
    #[new]
    #[pyo3(signature = (fov=45.0, position=vec![3.0, 2.0, 5.0], look_at=vec![0.0, 0.0, 0.0], near=0.1, far=100.0))]
    fn new(fov: f32, position: Vec<f32>, look_at: Vec<f32>, near: f32, far: f32) -> Self {
        Self {
            inner: CameraRig {
                camera: Camera {
                    position: Vec3::new(position[0], position[1], position[2]),
                    look_at: Vec3::new(look_at[0], look_at[1], look_at[2]),
                    up: Vec3::Y,
                },
                projection: Projection::Perspective { fov, near, far },
            },
        }
    }
}

#[pyclass(name = "ObliqueCamera", from_py_object)]
#[derive(Clone)]
pub struct PyObliqueCamera {
    pub inner: CameraRig,
}

#[pymethods]
impl PyObliqueCamera {
    #[new]
    #[pyo3(signature = (alpha=210.0, l=0.5, position=vec![0.0, 0.0, 10.0], look_at=vec![0.0, 0.0, 0.0], height=8.0, near=0.1, far=100.0))]
    fn new(
        alpha: f32,
        l: f32,
        position: Vec<f32>,
        look_at: Vec<f32>,
        height: f32,
        near: f32,
        far: f32,
    ) -> Self {
        Self {
            inner: CameraRig {
                camera: Camera {
                    position: Vec3::new(position[0], position[1], position[2]),
                    look_at: Vec3::new(look_at[0], look_at[1], look_at[2]),
                    up: Vec3::Y,
                },
                projection: Projection::Oblique {
                    alpha,
                    l,
                    height,
                    near,
                    far,
                },
            },
        }
    }
}
