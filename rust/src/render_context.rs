use pyo3::prelude::*;

use crate::scene_node::{Object3D, is_node_chain_active};
use crate::tessellation::{Mesh, Surface, Texture};

pub const STRIDE: usize = 21;

// Property indices for building DrawUniforms from mesh fields.
pub const CLIP_THRESHOLD: usize = 0;
pub const OPACITY: usize = 1;
pub const POSITION_X: usize = 2;
pub const SCALE_X: usize = 5;
pub const ROTATION_X: usize = 8;
pub const TINT_R: usize = 12;
// offset 15 is reserved (_pad0 in DrawUniforms)
pub const FRAME_INDEX: usize = 16;
pub const ACTIVE: usize = 17;
pub const Z_INDEX: usize = 18;
pub const SHADING: usize = 19;
pub const SIDE: usize = 20;

// ── Renderer ─────────────────────────────────────────────────────────

#[pyclass]
pub struct Renderer {
    /// Cloned mesh data — used for initial GPU upload.
    pub meshes: Vec<Mesh>,
    /// Cloned texture data (parallel to meshes). None = solid mesh.
    pub textures: Vec<Option<Texture>>,
    /// Python-side Surface references — used to read per-frame property updates.
    surface_refs: Vec<Py<Surface>>,
    /// Parallel Object3D references — one per Surface, for reading transforms.
    object3d_refs: Vec<Py<Object3D>>,
    /// Camera — set via set_camera(), read per-frame during render.
    camera: Option<Py<crate::camera::Camera>>,
}

#[pymethods]
impl Renderer {
    #[new]
    pub fn new() -> Self {
        Renderer {
            meshes: Vec::new(),
            textures: Vec::new(),
            surface_refs: Vec::new(),
            object3d_refs: Vec::new(),
            camera: None,
        }
    }

    pub fn set_camera(&mut self, camera: Py<crate::camera::Camera>) {
        self.camera = Some(camera);
    }

    pub fn add(&mut self, py: Python<'_>, object3d: &Bound<'_, Object3D>) {
        let node = object3d.borrow();
        for surface_ref in &node.surfaces {
            let surface = surface_ref.borrow(py);
            // Clone mesh data for GPU upload.
            let mesh = surface.mesh.borrow(py);
            self.meshes.push(mesh.clone());
            // Clone texture from material if present.
            let mat = surface.material.borrow(py);
            let texture = mat.texture.as_ref().map(|t| t.borrow(py).clone());
            self.textures.push(texture);
            // Keep references to Surface and its Object3D for per-frame state reads.
            self.surface_refs.push(surface_ref.clone_ref(py));
            self.object3d_refs.push(object3d.as_unbound().clone_ref(py));
        }
    }

    #[pyo3(signature = (*, evaluate_frame, total_duration, output, width=1920, height=1080, fps=60, supersample=1))]
    #[allow(clippy::too_many_arguments)]
    pub fn render(
        &mut self,
        py: Python<'_>,
        evaluate_frame: Py<PyAny>,
        total_duration: f32,
        output: std::path::PathBuf,
        width: u32,
        height: u32,
        fps: u32,
        supersample: u32,
    ) -> PyResult<()> {
        let camera = self.camera.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err(
                "No camera set. Call set_camera() before render().",
            )
        })?;

        let render_width = width * supersample;
        let render_height = height * supersample;

        let num_instances = self.meshes.len() as u32;
        let ids: Vec<u32> = (0..num_instances).collect();

        let cfg = crate::common::RenderConfig {
            total_duration,
            fps,
            output_path: output,
            output_width: width,
            output_height: height,
        };

        #[cfg(target_os = "macos")]
        {
            let mut r = crate::metal_renderer::MetalRenderer::new(render_width, render_height)?;
            r.upload_meshes(self.meshes.clone(), &self.textures, ids, num_instances);
            r.render_all_frames(
                py,
                &evaluate_frame,
                &self.surface_refs,
                &self.object3d_refs,
                camera,
                cfg,
            )
        }
        #[cfg(not(target_os = "macos"))]
        {
            let mut r = crate::renderer::GpuRenderer::new(render_width, render_height)?;
            r.upload_meshes(self.meshes.clone(), &self.textures, ids, num_instances);
            r.render_all_frames(
                py,
                &evaluate_frame,
                &self.surface_refs,
                &self.object3d_refs,
                camera,
                cfg,
            )
        }
    }
}

/// Snapshot current Surface fields into a flat state buffer.
/// Reads transforms from the parallel Object3D refs (absolute coordinates).
/// No parent-child composition — transforms are already absolute.
pub fn snapshot_surfaces(
    py: Python<'_>,
    surface_refs: &[Py<Surface>],
    object3d_refs: &[Py<Object3D>],
    state: &mut Vec<f32>,
) {
    let n = surface_refs.len();
    state.resize(n * STRIDE, 0.0);

    for (i, (surface_ref, node_ref)) in surface_refs.iter().zip(object3d_refs.iter()).enumerate() {
        let surface = surface_ref.borrow(py);
        let node = node_ref.borrow(py);
        let b = i * STRIDE;

        // Read absolute transforms from Object3D
        let node_active = is_node_chain_active(py, &node);

        // Write transforms directly (already absolute)
        state[b + POSITION_X] = node.position[0];
        state[b + POSITION_X + 1] = node.position[1];
        state[b + POSITION_X + 2] = node.position[2];
        state[b + SCALE_X] = node.scale[0];
        state[b + SCALE_X + 1] = node.scale[1];
        state[b + SCALE_X + 2] = node.scale[2];
        state[b + ROTATION_X] = node.quaternion[0];
        state[b + ROTATION_X + 1] = node.quaternion[1];
        state[b + ROTATION_X + 2] = node.quaternion[2];
        state[b + ROTATION_X + 3] = node.quaternion[3];

        // Cascading visibility: Surface active AND all ancestor nodes active
        let effective_active = surface.active && node_active;
        state[b + ACTIVE] = if effective_active { 1.0 } else { 0.0 };
        state[b + OPACITY] = if effective_active {
            surface.material.borrow(py).opacity
        } else {
            0.0
        };

        state[b + Z_INDEX] = surface.z_index;
        state[b + CLIP_THRESHOLD] = surface.clip_threshold;

        let mat = surface.material.borrow(py);
        let c = mat.color;
        state[b + TINT_R] = c.0 as f32 / 255.0;
        state[b + TINT_R + 1] = c.1 as f32 / 255.0;
        state[b + TINT_R + 2] = c.2 as f32 / 255.0;
        state[b + SHADING] = mat.shading.value as f32;
        state[b + SIDE] = mat.side.value as f32;
        state[b + FRAME_INDEX] = 0.0;
    }
}

// ── Constants ────────────────────────────────────────────────────────

#[pyclass(frozen, eq, hash, from_py_object)]
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct FillRule {
    pub(crate) value: u8,
}

#[allow(non_snake_case)]
#[pymethods]
impl FillRule {
    #[classattr]
    fn NON_ZERO() -> FillRule {
        FillRule { value: 0 }
    }
    #[classattr]
    fn EVEN_ODD() -> FillRule {
        FillRule { value: 1 }
    }
}

#[pyclass(frozen, eq, hash, from_py_object)]
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Shading {
    pub(crate) value: u8,
}

#[allow(non_snake_case)]
#[pymethods]
impl Shading {
    #[classattr]
    fn UNLIT() -> Shading {
        Shading { value: 0 }
    }
    #[classattr]
    fn FLAT() -> Shading {
        Shading { value: 1 }
    }
    #[classattr]
    fn SMOOTH() -> Shading {
        Shading { value: 2 }
    }
}

#[pyclass(frozen, eq, hash, from_py_object)]
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Side {
    pub(crate) value: u8,
}

#[allow(non_snake_case)]
#[pymethods]
impl Side {
    #[classattr]
    fn FRONT() -> Side {
        Side { value: 0 }
    }
    #[classattr]
    fn BACK() -> Side {
        Side { value: 1 }
    }
    #[classattr]
    fn BOTH() -> Side {
        Side { value: 2 }
    }
}

#[pyclass(frozen)]
pub struct PathCommand;

#[pymethods]
impl PathCommand {
    #[classattr]
    const MOVE_TO: u8 = 0;
    #[classattr]
    const LINE_TO: u8 = 1;
    #[classattr]
    const CUBIC_TO: u8 = 2;
    #[classattr]
    const QUAD_TO: u8 = 3;
    #[classattr]
    const CLOSE: u8 = 4;
}
