use pyo3::prelude::*;

mod camera;
mod common;
#[cfg(target_os = "macos")]
mod metal_renderer;
mod render_context;
mod renderer;
mod scene_node;
mod tessellation;

#[pymodule]
fn engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(tessellation::tessellate_svg, m)?)?;
    m.add_function(wrap_pyfunction!(tessellation::tessellate, m)?)?;
    m.add_function(wrap_pyfunction!(tessellation::build_surface, m)?)?;
    m.add_function(wrap_pyfunction!(tessellation::build_textured_quad, m)?)?;
    m.add_class::<tessellation::Material>()?;
    m.add_class::<tessellation::Surface>()?;
    m.add_class::<tessellation::Mesh>()?;
    m.add_class::<tessellation::Texture>()?;
    m.add_class::<tessellation::TessellationResult>()?;
    m.add_class::<tessellation::SvgGlyphData>()?;
    m.add_class::<camera::Camera>()?;
    m.add_class::<scene_node::Object3D>()?;
    m.add_class::<render_context::Renderer>()?;
    m.add_class::<render_context::FillRule>()?;
    m.add_class::<render_context::Shading>()?;
    m.add_class::<render_context::Side>()?;
    m.add_class::<render_context::PathCommand>()?;
    Ok(())
}
