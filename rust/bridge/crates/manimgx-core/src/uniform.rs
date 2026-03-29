/// GPU uniform buffer types shared across render backends.
/// Layout must match WGSL and MSL shader struct definitions exactly.

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
pub struct CameraUniform {
    pub view_proj: [[f32; 4]; 4],
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
pub struct ObjectUniform {
    pub model: [[f32; 4]; 4],
    pub material_color: [f32; 4],
    pub use_vertex_colors: u32,
    pub _pad: [u32; 3],
}
