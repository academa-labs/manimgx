use numpy::PyArray1;
use pyo3::prelude::*;

use crate::tessellation::Surface;

// ── Quaternion helpers ──────────────────────────────────────────────────

pub fn quat_mul(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    let [ax, ay, az, aw] = a;
    let [bx, by, bz, bw] = b;
    [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]
}

pub fn quat_rotate_vec3(q: [f32; 4], v: [f32; 3]) -> [f32; 3] {
    let [qx, qy, qz, qw] = q;
    let [vx, vy, vz] = v;
    let tx = 2.0 * (qy * vz - qz * vy);
    let ty = 2.0 * (qz * vx - qx * vz);
    let tz = 2.0 * (qx * vy - qy * vx);
    [
        vx + qw * tx + (qy * tz - qz * ty),
        vy + qw * ty + (qz * tx - qx * tz),
        vz + qw * tz + (qx * ty - qy * tx),
    ]
}

// ── Object3D ───────────────────────────────────────────────────────────

#[pyclass]
pub struct Object3D {
    pub position: [f32; 3],
    pub scale: [f32; 3],
    pub quaternion: [f32; 4],
    pub(crate) parent: Option<Py<Object3D>>,
    pub(crate) children: Vec<Py<Object3D>>,
    pub(crate) surfaces: Vec<Py<Surface>>,
    #[pyo3(get, set)]
    pub active: bool,
}

#[pymethods]
impl Object3D {
    #[new]
    #[pyo3(signature = (*surfaces))]
    fn new(surfaces: Vec<Py<Surface>>) -> Self {
        Object3D {
            position: [0.0, 0.0, 0.0],
            scale: [1.0, 1.0, 1.0],
            quaternion: [0.0, 0.0, 0.0, 1.0],
            parent: None,
            children: Vec::new(),
            surfaces,
            active: true,
        }
    }

    #[getter]
    fn surfaces(&self, py: Python<'_>) -> Vec<Py<Surface>> {
        self.surfaces.iter().map(|s| s.clone_ref(py)).collect()
    }

    // ── Transform getters/setters ───────────────────────────────────

    #[getter]
    fn position<'py>(&self, py: Python<'py>) -> Bound<'py, PyArray1<f32>> {
        PyArray1::from_slice(py, &self.position)
    }

    #[setter]
    fn set_position(&mut self, value: Vec<f32>) {
        self.position.copy_from_slice(&value[..3]);
    }

    #[getter]
    fn scale<'py>(&self, py: Python<'py>) -> Bound<'py, PyArray1<f32>> {
        PyArray1::from_slice(py, &self.scale)
    }

    #[setter]
    fn set_scale(&mut self, value: Vec<f32>) {
        self.scale.copy_from_slice(&value[..3]);
    }

    #[getter]
    fn quaternion<'py>(&self, py: Python<'py>) -> Bound<'py, PyArray1<f32>> {
        PyArray1::from_slice(py, &self.quaternion)
    }

    #[setter]
    fn set_quaternion(&mut self, value: Vec<f32>) {
        self.quaternion.copy_from_slice(&value[..4]);
    }

    // ── Parent (manages children lists) ─────────────────────────────

    #[getter]
    fn parent(&self, py: Python<'_>) -> Option<Py<Object3D>> {
        self.parent.as_ref().map(|p| p.clone_ref(py))
    }

    #[setter]
    fn set_parent(slf: &Bound<'_, Self>, value: Option<Py<Object3D>>) {
        let py = slf.py();

        // Remove from old parent's children
        {
            let this = slf.borrow();
            if let Some(ref old_parent_ref) = this.parent {
                let mut old_parent = old_parent_ref.borrow_mut(py);
                old_parent.children.retain(|c| !c.is(slf));
            }
        }

        // Add to new parent's children
        if let Some(ref new_parent_ref) = value {
            let mut new_parent = new_parent_ref.borrow_mut(py);
            new_parent.children.push(slf.clone().unbind());
        }

        // Set parent reference
        slf.borrow_mut().parent = value;
    }

    // ── Group transforms (propagate to all descendants) ─────────────

    fn shift(&mut self, py: Python<'_>, offset: Vec<f32>) {
        let off = [offset[0], offset[1], offset[2]];
        self.shift_recursive(py, off);
    }

    #[pyo3(signature = (quaternion, about=None))]
    fn rotate(&mut self, py: Python<'_>, quaternion: Vec<f32>, about: Option<Vec<f32>>) {
        let q = [quaternion[0], quaternion[1], quaternion[2], quaternion[3]];
        let pivot = about.map(|a| [a[0], a[1], a[2]]).unwrap_or(self.position);
        self.rotate_recursive(py, q, pivot);
    }

    #[pyo3(signature = (factor, about=None))]
    fn apply_scale(&mut self, py: Python<'_>, factor: Vec<f32>, about: Option<Vec<f32>>) {
        let f = [factor[0], factor[1], factor[2]];
        let pivot = about.map(|a| [a[0], a[1], a[2]]).unwrap_or(self.position);
        self.scale_recursive(py, f, pivot);
    }
}

// ── Recursive helpers (not exposed to Python) ───────────────────────────

impl Object3D {
    fn shift_recursive(&mut self, py: Python<'_>, offset: [f32; 3]) {
        self.position[0] += offset[0];
        self.position[1] += offset[1];
        self.position[2] += offset[2];
        for child_ref in &self.children {
            child_ref.borrow_mut(py).shift_recursive(py, offset);
        }
    }

    fn rotate_recursive(&mut self, py: Python<'_>, q: [f32; 4], pivot: [f32; 3]) {
        // Rotate position around pivot
        let rel = [
            self.position[0] - pivot[0],
            self.position[1] - pivot[1],
            self.position[2] - pivot[2],
        ];
        let rotated = quat_rotate_vec3(q, rel);
        self.position = [
            pivot[0] + rotated[0],
            pivot[1] + rotated[1],
            pivot[2] + rotated[2],
        ];
        // Compose rotation
        self.quaternion = quat_mul(q, self.quaternion);
        for child_ref in &self.children {
            child_ref.borrow_mut(py).rotate_recursive(py, q, pivot);
        }
    }

    fn scale_recursive(&mut self, py: Python<'_>, factor: [f32; 3], pivot: [f32; 3]) {
        // Scale position relative to pivot
        self.position = [
            pivot[0] + factor[0] * (self.position[0] - pivot[0]),
            pivot[1] + factor[1] * (self.position[1] - pivot[1]),
            pivot[2] + factor[2] * (self.position[2] - pivot[2]),
        ];
        // Compose scale
        self.scale = [
            self.scale[0] * factor[0],
            self.scale[1] * factor[1],
            self.scale[2] * factor[2],
        ];
        for child_ref in &self.children {
            child_ref.borrow_mut(py).scale_recursive(py, factor, pivot);
        }
    }
}

/// Walk up the parent chain checking active flags.
pub fn is_node_chain_active(py: Python<'_>, node: &Object3D) -> bool {
    if !node.active {
        return false;
    }
    let mut current = node.parent.as_ref().map(|p| p.clone_ref(py));
    loop {
        let Some(node_ref) = current else { break };
        let n = node_ref.borrow(py);
        if !n.active {
            return false;
        }
        current = n.parent.as_ref().map(|p| p.clone_ref(py));
        drop(n);
    }
    true
}
