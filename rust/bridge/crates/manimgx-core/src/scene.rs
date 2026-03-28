use crate::camera::CameraRig;
use crate::material::Material;
use crate::transform::Transform;
use crate::vertex::Vertex;

pub type ObjectId = usize;

/// RGBA bitmap data for textured objects (e.g. rendered text).
#[derive(Clone, Debug)]
pub struct TextureData {
    pub rgba: Vec<u8>,
    pub width: u32,
    pub height: u32,
}

#[derive(Clone, Copy, Debug, Default)]
pub enum RenderHint {
    #[default]
    Default,
    FlatUnlit,
    /// Textured quad (e.g. text bitmap). Uses text.wgsl with texture sampling.
    Textured,
}

#[derive(Clone, Debug)]
pub struct SceneObject {
    pub id: ObjectId,
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u32>,
    pub transform: Transform,
    pub base_transform: Transform,
    pub material: Material,
    pub base_material: Material,
    pub render_hint: RenderHint,
    /// Optional texture data for Textured render hint (uploaded once, not per frame).
    pub texture_data: Option<TextureData>,
}

pub struct Scene {
    pub width: u32,
    pub height: u32,
    pub fps: u32,
    pub background: [f32; 4],
    pub camera: CameraRig,
    pub base_camera: CameraRig,
    pub objects: Vec<SceneObject>,
    next_id: ObjectId,
}

impl Scene {
    pub fn new(width: u32, height: u32, fps: u32, background: [f32; 3]) -> Self {
        Self {
            width,
            height,
            fps,
            background: [background[0], background[1], background[2], 1.0],
            camera: CameraRig::default(),
            base_camera: CameraRig::default(),
            objects: Vec::new(),
            next_id: 0,
        }
    }

    pub fn set_camera(&mut self, camera: CameraRig) {
        self.camera = camera.clone();
        self.base_camera = camera;
    }

    pub fn add_object_with_hint(
        &mut self,
        vertices: Vec<Vertex>,
        indices: Vec<u32>,
        material: Material,
        render_hint: RenderHint,
        position: [f32; 3],
    ) -> ObjectId {
        let id = self.next_id;
        self.next_id += 1;
        let transform = Transform {
            translation: glam::Vec3::new(position[0], position[1], position[2]),
            ..Transform::default()
        };
        self.objects.push(SceneObject {
            id,
            vertices,
            indices,
            transform: transform.clone(),
            base_transform: transform,
            material: material.clone(),
            base_material: material,
            render_hint,
            texture_data: None,
        });
        id
    }

    /// Add a textured object (e.g. text bitmap) with texture data attached.
    pub fn add_textured_object(
        &mut self,
        vertices: Vec<Vertex>,
        indices: Vec<u32>,
        material: Material,
        position: [f32; 3],
        texture: TextureData,
    ) -> ObjectId {
        let id = self.next_id;
        self.next_id += 1;
        let transform = Transform {
            translation: glam::Vec3::new(position[0], position[1], position[2]),
            ..Transform::default()
        };
        self.objects.push(SceneObject {
            id,
            vertices,
            indices,
            transform: transform.clone(),
            base_transform: transform,
            material: material.clone(),
            base_material: material,
            render_hint: RenderHint::Textured,
            texture_data: Some(texture),
        });
        id
    }

    pub fn set_transform(&mut self, id: ObjectId, transform: Transform) {
        if let Some(obj) = self.objects.get_mut(id) {
            obj.transform = transform;
        }
    }

    pub fn set_material(&mut self, id: ObjectId, material: Material) {
        if let Some(obj) = self.objects.get_mut(id) {
            obj.material = material;
        }
    }

    pub fn reset_to_base(&mut self) {
        self.camera = self.base_camera.clone();
        for obj in &mut self.objects {
            obj.transform = obj.base_transform.clone();
            obj.material = obj.base_material.clone();
        }
    }

    pub fn aspect_ratio(&self) -> f32 {
        self.width as f32 / self.height as f32
    }
}
