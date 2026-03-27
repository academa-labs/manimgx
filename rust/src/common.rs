use bytemuck::{Pod, Zeroable};
use std::io::{BufWriter, Read as IoRead, Write};
use std::process::{Child, Command, Stdio};

use crate::render_context::{
    CLIP_THRESHOLD, OPACITY, POSITION_X, ROTATION_X, SCALE_X, SHADING, STRIDE, TINT_R,
};
use crate::tessellation::{Mesh, SubMesh};

pub const MSAA_SAMPLES: u32 = 4;
pub const PIPELINE_DEPTH: usize = 5;

/// Configuration passed from Renderer.render() to the platform renderer.
pub struct RenderConfig {
    pub total_duration: f32,
    pub fps: u32,
    pub output_path: std::path::PathBuf,
    pub output_width: u32,
    pub output_height: u32,
}

#[repr(C)]
#[derive(Copy, Clone, Pod, Zeroable)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],    // uv.x = arc-length progress, uv.y = 0.0 (reserved)
    pub color: [f32; 4], // per-vertex RGBA color
}

#[repr(C)]
#[derive(Copy, Clone, Pod, Zeroable)]
pub struct DrawUniforms {
    pub clip_threshold: f32,
    pub opacity: f32,
    pub shading: f32,
    pub _pad0: f32,
    pub position: [f32; 4],
    pub scale: [f32; 4],
    pub rotation: [f32; 4],
    pub tint: [f32; 4],
}

#[repr(C)]
#[derive(Copy, Clone, Pod, Zeroable)]
pub struct CameraUniforms {
    pub view_projection: [[f32; 4]; 4],
}

pub fn orthographic_projection(width: u32, height: u32, frame_height: f32) -> [[f32; 4]; 4] {
    let aspect = width as f32 / height as f32;
    let frame_width = frame_height * aspect;
    let sx = 2.0 / frame_width;
    let sy = 2.0 / frame_height;
    let near = -100.0;
    let far = 100.0;
    let sz = 1.0 / (far - near);
    let tz = -near / (far - near);
    [
        [sx, 0.0, 0.0, 0.0],
        [0.0, sy, 0.0, 0.0],
        [0.0, 0.0, sz, 0.0],
        [0.0, 0.0, tz, 1.0],
    ]
}

pub fn perspective_projection(
    width: u32,
    height: u32,
    fov_y_deg: f32,
    near: f32,
    far: f32,
) -> [[f32; 4]; 4] {
    let aspect = width as f32 / height as f32;
    let fov_y = fov_y_deg * std::f32::consts::PI / 180.0;
    let f = 1.0 / (fov_y / 2.0).tan();
    let nf = 1.0 / (near - far);
    [
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, far * nf, -1.0],
        [0.0, 0.0, near * far * nf, 0.0],
    ]
}

fn quat_to_rotation_matrix(q: [f32; 4]) -> [[f32; 4]; 4] {
    let [x, y, z, w] = q;
    let x2 = x + x;
    let y2 = y + y;
    let z2 = z + z;
    let xx = x * x2;
    let xy = x * y2;
    let xz = x * z2;
    let yy = y * y2;
    let yz = y * z2;
    let zz = z * z2;
    let wx = w * x2;
    let wy = w * y2;
    let wz = w * z2;
    [
        [1.0 - (yy + zz), xy + wz, xz - wy, 0.0],
        [xy - wz, 1.0 - (xx + zz), yz + wx, 0.0],
        [xz + wy, yz - wx, 1.0 - (xx + yy), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
}

fn mat4_mul(a: [[f32; 4]; 4], b: [[f32; 4]; 4]) -> [[f32; 4]; 4] {
    let mut out = [[0.0f32; 4]; 4];
    for i in 0..4 {
        for j in 0..4 {
            out[i][j] =
                a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] + a[i][3] * b[3][j];
        }
    }
    out
}

pub fn build_view_projection(
    width: u32,
    height: u32,
    frame_height: f32,
    position: [f32; 3],
    rotation: [f32; 4],
    projection: u8,
    fov: f32,
) -> [[f32; 4]; 4] {
    let proj = if projection == 1 {
        perspective_projection(width, height, fov, 0.1, 200.0)
    } else {
        orthographic_projection(width, height, frame_height)
    };

    // Build view matrix: inverse of camera transform
    // View = inverse(Translation * Rotation) = inverse(Rotation) * inverse(Translation)
    // Conjugate the quaternion (negate x,y,z) for inverse rotation
    let inv_rot = [-rotation[0], -rotation[1], -rotation[2], rotation[3]];
    let rot_mat = quat_to_rotation_matrix(inv_rot);

    // Apply translation of -position through the inverse rotation
    let tx = -position[0];
    let ty = -position[1];
    let tz = -position[2];
    // Rotated translation
    let rtx = rot_mat[0][0] * tx + rot_mat[0][1] * ty + rot_mat[0][2] * tz;
    let rty = rot_mat[1][0] * tx + rot_mat[1][1] * ty + rot_mat[1][2] * tz;
    let rtz = rot_mat[2][0] * tx + rot_mat[2][1] * ty + rot_mat[2][2] * tz;

    let view = [
        [rot_mat[0][0], rot_mat[0][1], rot_mat[0][2], 0.0],
        [rot_mat[1][0], rot_mat[1][1], rot_mat[1][2], 0.0],
        [rot_mat[2][0], rot_mat[2][1], rot_mat[2][2], 0.0],
        [rtx, rty, rtz, 1.0],
    ];

    mat4_mul(view, proj)
}

#[repr(C)]
#[derive(Copy, Clone, Pod, Zeroable)]
pub struct TexturedVertex {
    pub position: [f32; 3],
    pub uv: [f32; 2],
}

pub fn build_textured_vertices(geo: &Mesh) -> Vec<TexturedVertex> {
    geo.texture_positions
        .chunks_exact(3)
        .zip(geo.texture_uvs.chunks_exact(2))
        .map(|(pos, uv)| TexturedVertex {
            position: [pos[0], pos[1], pos[2]],
            uv: [uv[0], uv[1]],
        })
        .collect()
}

pub fn build_vertices(submesh: &SubMesh) -> Vec<Vertex> {
    let has_per_vertex = !submesh.colors.is_empty();
    submesh
        .positions
        .chunks_exact(3)
        .zip(submesh.normals.chunks_exact(3))
        .zip(&submesh.progress)
        .enumerate()
        .map(|(i, ((pos, nor), &progress))| {
            let color = if has_per_vertex {
                let base = i * 4;
                [
                    submesh.colors[base],
                    submesh.colors[base + 1],
                    submesh.colors[base + 2],
                    submesh.colors[base + 3],
                ]
            } else {
                submesh.color
            };
            Vertex {
                position: [pos[0], pos[1], pos[2]],
                normal: [nor[0], nor[1], nor[2]],
                uv: [progress, 0.0],
                color,
            }
        })
        .collect()
}

pub fn build_draw_uniforms(state: &[f32], mobject_id: u32) -> DrawUniforms {
    let base = mobject_id as usize * STRIDE;
    DrawUniforms {
        clip_threshold: state[base + CLIP_THRESHOLD],
        opacity: state[base + OPACITY],
        shading: state[base + SHADING],
        _pad0: 0.0,
        position: [
            state[base + POSITION_X],
            state[base + POSITION_X + 1],
            state[base + POSITION_X + 2],
            0.0,
        ],
        scale: [
            state[base + SCALE_X],
            state[base + SCALE_X + 1],
            state[base + SCALE_X + 2],
            0.0,
        ],
        rotation: [
            state[base + ROTATION_X],
            state[base + ROTATION_X + 1],
            state[base + ROTATION_X + 2],
            state[base + ROTATION_X + 3],
        ],
        tint: [
            state[base + TINT_R],
            state[base + TINT_R + 1],
            state[base + TINT_R + 2],
            0.0,
        ],
    }
}

pub struct FfmpegPipeline {
    pub frame_tx: std::sync::mpsc::Sender<Vec<u8>>,
    pub buf_pool_rx: std::sync::mpsc::Receiver<Vec<u8>>,
    writer_handle: Option<std::thread::JoinHandle<Result<(), String>>>,
    stderr_handle: Option<std::thread::JoinHandle<String>>,
    child: Child,
}

impl FfmpegPipeline {
    pub fn spawn(
        width: u32,
        height: u32,
        fps: u32,
        output_path: &str,
        frame_size: usize,
        output_width: u32,
        output_height: u32,
    ) -> Result<Self, String> {
        if let Some(parent) = std::path::Path::new(output_path).parent()
            && !parent.as_os_str().is_empty()
        {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("Failed to create output directory: {e}"))?;
        }

        let is_image_sequence = output_path.ends_with(".png") || output_path.ends_with(".jpg");
        let pixel_format = if is_image_sequence { "rgba" } else { "nv12" };
        let video_size = format!("{width}x{height}");
        let fps_str = fps.to_string();

        let mut args: Vec<&str> = vec![
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            pixel_format,
            "-video_size",
            &video_size,
            "-framerate",
            &fps_str,
            "-thread_queue_size",
            "64",
            "-i",
            "pipe:0",
        ];
        if !is_image_sequence {
            args.extend([
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "23",
                "-threads",
                "0",
                "-flags",
                "+bitexact",
                "-fflags",
                "+bitexact",
            ]);
        }
        let scale_str;
        if output_width != width || output_height != height {
            scale_str = format!("scale={output_width}:{output_height}:flags=area");
            args.extend(["-vf", &scale_str]);
        }
        args.push(output_path);

        let mut child = Command::new("ffmpeg")
            .args(&args)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn ffmpeg: {e}"))?;

        let stdin = child.stdin.take().ok_or("Failed to open ffmpeg stdin")?;
        let stderr = child.stderr.take();

        let stderr_handle = std::thread::spawn(move || {
            let Some(stderr) = stderr else {
                return String::new();
            };
            let mut buf = String::new();
            std::io::BufReader::new(stderr)
                .read_to_string(&mut buf)
                .ok();
            buf
        });

        let (frame_tx, frame_rx) = std::sync::mpsc::channel::<Vec<u8>>();
        let (buf_return_tx, buf_pool_rx) = std::sync::mpsc::channel::<Vec<u8>>();
        for _ in 0..PIPELINE_DEPTH + 1 {
            buf_return_tx.send(vec![0u8; frame_size]).unwrap();
        }

        let writer_handle = std::thread::spawn(move || -> Result<(), String> {
            let mut writer = BufWriter::with_capacity(frame_size * 2, stdin);
            while let Ok(frame) = frame_rx.recv() {
                writer
                    .write_all(&frame)
                    .map_err(|e| format!("Pipe write error: {e}"))?;
                let _ = buf_return_tx.send(frame);
            }
            writer
                .flush()
                .map_err(|e| format!("Pipe flush error: {e}"))?;
            Ok(())
        });

        Ok(FfmpegPipeline {
            frame_tx,
            buf_pool_rx,
            writer_handle: Some(writer_handle),
            stderr_handle: Some(stderr_handle),
            child,
        })
    }

    pub fn finish(mut self) -> Result<(), String> {
        drop(self.frame_tx);
        let writer_result = self
            .writer_handle
            .take()
            .unwrap()
            .join()
            .map_err(|_| "Writer thread panicked".to_string())?;

        let status = self
            .child
            .wait()
            .map_err(|e| format!("ffmpeg wait error: {e}"))?;
        let stderr_output = self
            .stderr_handle
            .take()
            .unwrap()
            .join()
            .unwrap_or_default();

        writer_result?;
        if !status.success() {
            return Err(format!("ffmpeg failed (exit {status}): {stderr_output}"));
        }

        Ok(())
    }
}
