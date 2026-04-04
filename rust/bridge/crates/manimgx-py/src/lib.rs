use pyo3::prelude::*;

mod py_camera;
mod py_objects;
mod py_scene;

#[pymodule]
fn manimgx(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Scene
    m.add_class::<py_scene::PyScene>()?;
    // Cameras
    m.add_class::<py_camera::PyPerspectiveCamera>()?;
    m.add_class::<py_camera::PyObliqueCamera>()?;
    // 3D primitives
    m.add_class::<py_objects::PyCube>()?;
    m.add_class::<py_objects::PyBox3D>()?;
    m.add_class::<py_objects::PySphere>()?;
    m.add_class::<py_objects::PyCylinder>()?;
    m.add_class::<py_objects::PyPlane>()?;
    m.add_class::<py_objects::PyBezierCurve>()?;
    m.add_class::<py_objects::PyParametricSurface>()?;
    // 2D primitives
    m.add_class::<py_objects::PyPolygon>()?;
    m.add_class::<py_objects::PyPolygram>()?;
    m.add_class::<py_objects::PyTriangle>()?;
    m.add_class::<py_objects::PyCircle>()?;
    m.add_class::<py_objects::PyRectangle>()?;
    m.add_class::<py_objects::PyLine>()?;
    m.add_class::<py_objects::PyArc>()?;
    m.add_class::<py_objects::PyArrow>()?;
    m.add_class::<py_objects::PyDot>()?;
    // 2D graph primitives
    m.add_class::<py_objects::PyNumberLine>()?;
    m.add_class::<py_objects::PyAxes>()?;
    m.add_class::<py_objects::PyGrid>()?;
    m.add_class::<py_objects::PyFunctionPlot>()?;
    // New 2D primitives
    m.add_class::<py_objects::PyCurvedArrow>()?;
    m.add_class::<py_objects::PyDashedLine>()?;
    m.add_class::<py_objects::PyBrace>()?;
    m.add_class::<py_objects::PyFilledRegion>()?;
    m.add_class::<py_objects::PyRiemannRects>()?;
    // Text
    m.add_class::<py_objects::PyText>()?;
    Ok(())
}
