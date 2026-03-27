use numpy::PyArray1;
use pyo3::prelude::*;

#[pyclass]
pub struct Camera {
    #[pyo3(get, set)]
    pub frame_height: f32,
    #[pyo3(get, set)]
    pub background: (u8, u8, u8),
    pub position: [f32; 3],
    pub quaternion: [f32; 4],
    #[pyo3(get, set)]
    pub projection: u8, // 0 = orthographic (default), 1 = perspective
    #[pyo3(get, set)]
    pub fov: f32, // field of view in degrees, default 45.0, used when projection=1
}

#[pymethods]
impl Camera {
    #[new]
    #[pyo3(signature = (*, frame_height=8.0, background=(0, 0, 0), projection=0, fov=45.0))]
    fn new(frame_height: f32, background: (u8, u8, u8), projection: u8, fov: f32) -> Self {
        Camera {
            frame_height,
            background,
            position: [0.0, 0.0, 0.0],
            quaternion: [0.0, 0.0, 0.0, 1.0],
            projection,
            fov,
        }
    }

    #[getter]
    fn position<'py>(&self, py: Python<'py>) -> Bound<'py, PyArray1<f32>> {
        PyArray1::from_slice(py, &self.position)
    }

    #[setter]
    fn set_position(&mut self, value: Vec<f32>) {
        self.position.copy_from_slice(&value[..3]);
    }

    #[getter]
    fn quaternion<'py>(&self, py: Python<'py>) -> Bound<'py, PyArray1<f32>> {
        PyArray1::from_slice(py, &self.quaternion)
    }

    #[setter]
    fn set_quaternion(&mut self, value: Vec<f32>) {
        self.quaternion.copy_from_slice(&value[..4]);
    }
}
