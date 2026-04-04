use manimgx_core::animation::easing::EasingFunction;
use manimgx_core::animation::keyframe::{AnimatedProperty, Keyframe, CAMERA_OBJECT_ID};
use manimgx_core::animation::timeline::Timeline;
use manimgx_core::scene::{ObjectId, Scene};
use manimgx_core::encoder::{FfmpegCodec, FfmpegEncoder};
use manimgx_render::renderer::{EncoderBackend, FfmpegWriter, Renderer};
use glam::Vec3;
use pyo3::prelude::*;
use std::collections::HashMap;

use crate::py_camera::{PyObliqueCamera, PyPerspectiveCamera};
use crate::py_objects;

#[pyclass(name = "Scene")]
pub struct PyScene {
    scene: Scene,
    timeline: Timeline,
    sample_count: u32,
    uuid_map: HashMap<u64, ObjectId>,
}

#[pymethods]
impl PyScene {
    #[new]
    #[pyo3(signature = (width=1920, height=1080, fps=60, background=vec![0.0, 0.0, 0.0], msaa=4))]
    fn new(width: u32, height: u32, fps: u32, background: Vec<f32>, msaa: u32) -> Self {
        Self {
            scene: Scene::new(
                width,
                height,
                fps,
                [background[0], background[1], background[2]],
            ),
            timeline: Timeline::new(),
            sample_count: msaa,
            uuid_map: HashMap::new(),
        }
    }

    fn set_camera(&mut self, camera: &Bound<'_, PyAny>) -> PyResult<()> {
        let rig = if let Ok(cam) = camera.extract::<PyPerspectiveCamera>() {
            cam.inner
        } else if let Ok(cam) = camera.extract::<PyObliqueCamera>() {
            cam.inner
        } else {
            return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                "Unsupported camera type. Use PerspectiveCamera or ObliqueCamera.",
            ));
        };
        self.scene.set_camera(rig);
        Ok(())
    }

    /// Add an object to the scene at the current cursor time with opacity=1 (visible).
    fn add(&mut self, obj: &Bound<'_, PyAny>) -> PyResult<()> {
        let data = py_objects::extract_data(obj)?;
        let uuid = data.uuid;

        if self.uuid_map.contains_key(&uuid) {
            return Ok(()); // already added
        }

        let object_id = if let Some(texture) = data.texture_data {
            self.scene.add_textured_object(
                data.vertices,
                data.indices,
                data.material,
                data.position,
                texture,
            )
        } else {
            self.scene.add_object_with_hint(
                data.vertices,
                data.indices,
                data.material,
                data.render_hint,
                data.position,
            )
        };
        self.uuid_map.insert(uuid, object_id);
        Ok(())
    }

    /// Auto-add an object with opacity=0 (hidden), returning its ObjectId.
    fn auto_add_hidden(&mut self, obj: &Bound<'_, PyAny>) -> PyResult<ObjectId> {
        let data = py_objects::extract_data(obj)?;
        let uuid = data.uuid;

        let mut mat = data.material;
        mat.opacity = 0.0;

        let object_id = if let Some(texture) = data.texture_data {
            self.scene.add_textured_object(
                data.vertices,
                data.indices,
                mat,
                data.position,
                texture,
            )
        } else {
            self.scene.add_object_with_hint(
                data.vertices,
                data.indices,
                mat,
                data.render_hint,
                data.position,
            )
        };
        self.uuid_map.insert(uuid, object_id);
        Ok(object_id)
    }

    #[pyo3(signature = (obj, translation=None, rotation=None, scale=None, color=None, opacity=None, duration=1.0, easing="linear".to_string()))]
    #[allow(clippy::too_many_arguments)]
    fn animate(
        &mut self,
        obj: &Bound<'_, PyAny>,
        translation: Option<Vec<f32>>,
        rotation: Option<Vec<f32>>,
        scale: Option<Vec<f32>>,
        color: Option<Vec<f32>>,
        opacity: Option<f32>,
        duration: f32,
        easing: String,
    ) -> PyResult<()> {
        let uuid = py_objects::get_uuid(obj)?;

        // If not yet in scene, auto-add with opacity=0
        let object_id = if let Some(&id) = self.uuid_map.get(&uuid) {
            id
        } else {
            self.auto_add_hidden(obj)?
        };

        let easing_fn = EasingFunction::parse(&easing);
        let start_time = self.timeline.cursor;

        if let Some(t) = translation {
            self.timeline.add_keyframe(Keyframe {
                object_id,
                property: AnimatedProperty::Translation(Vec3::new(t[0], t[1], t[2])),
                start_time,
                duration,
                easing: easing_fn.clone(),
            });
        }

        if let Some(r) = rotation {
            self.timeline.add_keyframe(Keyframe {
                object_id,
                property: AnimatedProperty::Rotation(Vec3::new(r[0], r[1], r[2])),
                start_time,
                duration,
                easing: easing_fn.clone(),
            });
        }

        if let Some(s) = scale {
            self.timeline.add_keyframe(Keyframe {
                object_id,
                property: AnimatedProperty::Scale(Vec3::new(s[0], s[1], s[2])),
                start_time,
                duration,
                easing: easing_fn.clone(),
            });
        }

        if let Some(c) = color {
            self.timeline.add_keyframe(Keyframe {
                object_id,
                property: AnimatedProperty::Color(Vec3::new(c[0], c[1], c[2])),
                start_time,
                duration,
                easing: easing_fn.clone(),
            });
        }

        if let Some(o) = opacity {
            self.timeline.add_keyframe(Keyframe {
                object_id,
                property: AnimatedProperty::Opacity(o),
                start_time,
                duration,
                easing: easing_fn,
            });
        }

        Ok(())
    }

    /// Remove an object from the scene (zero-duration opacity→0 at cursor).
    fn remove(&mut self, obj: &Bound<'_, PyAny>) -> PyResult<()> {
        let uuid = py_objects::get_uuid(obj)?;
        let object_id = match self.uuid_map.get(&uuid) {
            Some(&id) => id,
            None => return Ok(()), // not in scene, nothing to do
        };

        self.timeline.add_keyframe(Keyframe {
            object_id,
            property: AnimatedProperty::Opacity(0.0),
            start_time: self.timeline.cursor,
            duration: 0.0,
            easing: EasingFunction::Linear,
        });

        Ok(())
    }

    /// Animate camera position and/or look_at target over time.
    #[pyo3(signature = (position=None, look_at=None, duration=1.0, easing="linear".to_string()))]
    fn animate_camera(
        &mut self,
        position: Option<Vec<f32>>,
        look_at: Option<Vec<f32>>,
        duration: f32,
        easing: String,
    ) {
        let easing_fn = EasingFunction::parse(&easing);
        let start_time = self.timeline.cursor;

        if let Some(p) = position {
            self.timeline.add_keyframe(Keyframe {
                object_id: CAMERA_OBJECT_ID,
                property: AnimatedProperty::CameraPosition(Vec3::new(p[0], p[1], p[2])),
                start_time,
                duration,
                easing: easing_fn.clone(),
            });
        }

        if let Some(la) = look_at {
            self.timeline.add_keyframe(Keyframe {
                object_id: CAMERA_OBJECT_ID,
                property: AnimatedProperty::CameraLookAt(Vec3::new(la[0], la[1], la[2])),
                start_time,
                duration,
                easing: easing_fn,
            });
        }
    }

    fn wait(&mut self, seconds: f32) {
        self.timeline.advance_cursor(seconds);
    }

    fn get_cursor(&self) -> f32 {
        self.timeline.cursor
    }

    fn set_cursor(&mut self, time: f32) {
        self.timeline.cursor = time;
    }

    #[pyo3(signature = (output, encoder="cpu".to_string(), n_buffers=2, preset="medium".to_string(), crf=18, backend="wgpu".to_string(), pix_fmt="nv12".to_string(), muxer="fmp4".to_string()))]
    fn render(
        &mut self,
        py: Python<'_>,
        output: String,
        encoder: String,
        n_buffers: u32,
        preset: String,
        crf: u32,
        backend: String,
        pix_fmt: String,
        muxer: String,
    ) -> PyResult<()> {
        let path = Self::output_path(&output);
        let check_cancelled = || py.check_signals().is_err();

        if backend == "metal_native" {
            #[cfg(target_os = "macos")]
            {
                manimgx_metal::MetalBackend::validate_sample_count(self.sample_count)
                    .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;
                return self.render_metal_native(&path, &encoder, n_buffers, &preset, crf, &muxer, &check_cancelled);
            }
            #[cfg(not(target_os = "macos"))]
            {
                return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    "backend='metal_native' is only available on macOS",
                ));
            }
        }

        if !matches!(self.sample_count, 1 | 4) {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                format!(
                    "wgpu backend only supports msaa=1 or msaa=4. Use backend='metal_native' for msaa={}.",
                    self.sample_count
                ),
            ));
        }

        let enc_backend = Self::parse_encoder(&encoder)?;
        self.render_inner(&path, enc_backend, n_buffers, &preset, crf, &pix_fmt, &muxer, &check_cancelled);
        Ok(())
    }

    fn render_png(&mut self, output: String) -> PyResult<()> {
        if !matches!(self.sample_count, 1 | 4) {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                format!(
                    "wgpu backend only supports msaa=1 or msaa=4. Use backend='metal_native' for msaa={}.",
                    self.sample_count
                ),
            ));
        }
        let path = Self::output_path(&output);
        let renderer = Renderer::new(self.sample_count);
        self.timeline.evaluate(&mut self.scene, 0.0);
        renderer.render_to_png(&self.scene, &path);
        Ok(())
    }
}

impl PyScene {
    /// Render using the native Metal backend (bypasses wgpu entirely).
    #[cfg(target_os = "macos")]
    fn render_metal_native(
        &mut self,
        output: &str,
        encoder: &str,
        n_buffers: u32,
        preset: &str,
        crf: u32,
        muxer: &str,
        check_cancelled: &dyn Fn() -> bool,
    ) -> PyResult<()> {
        let total_duration = self.timeline.total_duration();
        if total_duration <= 0.0 {
            // Fall back to wgpu for single-frame PNG
            let renderer = Renderer::new(self.sample_count);
            self.timeline.evaluate(&mut self.scene, 0.0);
            renderer.render_to_png(&self.scene, output);
            return Ok(());
        }

        let fps = self.scene.fps;
        let total_frames = (total_duration * fps as f32).ceil() as u32;

        let start = std::time::Instant::now();

        match encoder {
            "metal" => {
                eprintln!(
                    "Rendering {} frames ({:.1}s @ {} fps) [backend: metal_native, encoder: metal (IOSurface, zero readback), n_buffers: {}]...",
                    total_frames, total_duration, fps, n_buffers,
                );
                manimgx_metal::render_video_metal(
                    &mut self.scene,
                    &self.timeline,
                    output,
                    total_frames,
                    fps,
                    self.sample_count,
                    n_buffers,
                    check_cancelled,
                );
            }
            "cpu" => {
                eprintln!(
                    "Rendering {} frames ({:.1}s @ {} fps) [backend: metal_native, encoder: cpu (in-process x264), n_buffers: {}, preset: {}, crf: {}, muxer: {}]...",
                    total_frames, total_duration, fps, n_buffers, preset, crf, muxer,
                );
                manimgx_metal::render_video_x264(
                    &mut self.scene,
                    &self.timeline,
                    output,
                    total_frames,
                    fps,
                    self.sample_count,
                    n_buffers,
                    &preset,
                    crf,
                    muxer,
                    check_cancelled,
                );
            }
            _ => {
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Unknown encoder '{}' for metal_native backend. Choose from: 'cpu', 'metal'",
                    encoder
                )));
            }
        }

        let elapsed = start.elapsed();
        let fps_actual = total_frames as f64 / elapsed.as_secs_f64();
        eprintln!(
            "Saved: {} ({:.2}s, {:.0} fps)",
            output,
            elapsed.as_secs_f64(),
            fps_actual,
        );

        Ok(())
    }

    /// Always place output files under `<repo_root>/output/`, creating it if needed.
    fn output_path(filename: &str) -> String {
        let p = std::path::Path::new(filename);
        let name = p.file_name().unwrap_or(p.as_os_str());
        // CARGO_MANIFEST_DIR points to crates/manimgx-py at compile time; go up two levels for repo root
        let repo_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let dir = repo_root.join("output");
        std::fs::create_dir_all(&dir).expect("Failed to create output/ directory");
        dir.join(name).to_string_lossy().into_owned()
    }

    fn parse_encoder(encoder: &str) -> PyResult<EncoderBackend> {
        match encoder {
            "cpu" => Ok(EncoderBackend::X264),
            "hw" => {
                #[cfg(target_os = "macos")]
                {
                    Ok(EncoderBackend::Ffmpeg(FfmpegCodec::H264VideoToolbox))
                }
                #[cfg(not(target_os = "macos"))]
                {
                    Ok(EncoderBackend::Ffmpeg(FfmpegCodec::H264Vaapi))
                }
            }
            _ => Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                "Unknown encoder '{}'. Choose from: 'cpu', 'hw'",
                encoder
            ))),
        }
    }

    fn render_inner(
        &mut self,
        output: &str,
        backend: EncoderBackend,
        n_buffers: u32,
        preset: &str,
        crf: u32,
        pix_fmt: &str,
        muxer: &str,
        check_cancelled: &dyn Fn() -> bool,
    ) {
        let total_duration = self.timeline.total_duration();
        if total_duration <= 0.0 {
            let renderer = Renderer::new(self.sample_count);
            self.timeline.evaluate(&mut self.scene, 0.0);
            renderer.render_to_png(&self.scene, output);
            return;
        }

        let fps = self.scene.fps;
        let total_frames = (total_duration * fps as f32).ceil() as u32;
        let use_nv12 = pix_fmt == "nv12";

        match &backend {
            EncoderBackend::Ffmpeg(FfmpegCodec::H264VideoToolbox) => {
                eprintln!(
                    "Rendering {} frames ({:.1}s @ {} fps) [backend: wgpu, encoder: hw (VideoToolbox via ffmpeg), n_buffers: {}, pix_fmt: {}]...",
                    total_frames, total_duration, fps, n_buffers, pix_fmt,
                );
            }
            EncoderBackend::Ffmpeg(FfmpegCodec::H264Vaapi) => {
                eprintln!(
                    "Rendering {} frames ({:.1}s @ {} fps) [backend: wgpu, encoder: hw (VAAPI via ffmpeg), n_buffers: {}, pix_fmt: {}]...",
                    total_frames, total_duration, fps, n_buffers, pix_fmt,
                );
            }
            EncoderBackend::X264 => {
                eprintln!(
                    "Rendering {} frames ({:.1}s @ {} fps) [backend: wgpu, encoder: cpu (in-process x264), n_buffers: {}, preset: {}, crf: {}, muxer: {}]...",
                    total_frames, total_duration, fps, n_buffers, preset, crf, muxer,
                );
            }
        }

        let start = std::time::Instant::now();
        let w = self.scene.width;
        let h = self.scene.height;

        // Validate NV12 dimension requirements
        if use_nv12 {
            assert!(
                w % 4 == 0 && h % 2 == 0,
                "NV12 requires width%4==0 and height%2==0, got {}x{}",
                w,
                h
            );
        }

        match backend {
            EncoderBackend::Ffmpeg(codec) => {
                let renderer = Renderer::new(self.sample_count);
                let effective_fmt = if use_nv12 { "nv12" } else { "rgba" };
                let pixel_size = if use_nv12 {
                    (w * h * 3 / 2) as usize
                } else {
                    (w * h * 4) as usize
                };
                let encoder = FfmpegEncoder::with_pixel_format(
                    output, w, h, fps, codec, crf, effective_fmt,
                );
                let mut writer = FfmpegWriter::new(encoder, pixel_size);
                renderer.render_video(
                    &mut self.scene,
                    &self.timeline,
                    &mut writer,
                    total_frames,
                    fps,
                    n_buffers,
                    use_nv12,
                    check_cancelled,
                );
            }
            EncoderBackend::X264 => {
                assert!(
                    w % 4 == 0 && h % 2 == 0,
                    "NV12 requires width%4==0 and height%2==0, got {}x{}",
                    w, h,
                );
                let renderer = Renderer::new(self.sample_count);
                renderer.render_video_x264(
                    &mut self.scene,
                    &self.timeline,
                    output,
                    total_frames,
                    fps,
                    n_buffers,
                    preset,
                    crf,
                    muxer,
                    check_cancelled,
                );
            }
        }

        let elapsed = start.elapsed();
        let fps_actual = total_frames as f64 / elapsed.as_secs_f64();
        eprintln!(
            "Saved: {} ({:.2}s, {:.0} fps)",
            output,
            elapsed.as_secs_f64(),
            fps_actual,
        );
    }
}
