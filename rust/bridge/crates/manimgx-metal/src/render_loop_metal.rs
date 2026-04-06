use manimgx_core::scene::Scene;
use manimgx_core::timeline_eval::TimelineEval;

use manimgx_core::uniform::{CameraUniform, ObjectUniform};
use crate::backend::MetalBackend;
use crate::metal_encoder::MetalEncoder;

/// Render a video using the native Metal backend with VideoToolbox encoding.
///
/// Zero-copy path: GPU renders into IOSurface-backed textures, VideoToolbox
/// reads the same IOSurface memory for hardware H.264 encoding. No pixel
/// readback, no ffmpeg, no CPU copies.
pub fn render_video_metal(
    scene: &mut Scene,
    timeline: &dyn TimelineEval,
    output: &str,
    total_frames: u32,
    fps: u32,
    sample_count: u32,
    n_buffers: u32,
    check_cancelled: &dyn Fn() -> bool,
) {
    if total_frames == 0 {
        return;
    }

    let width = scene.width;
    let height = scene.height;
    let n = n_buffers.max(1) as usize;

    // Create Metal backend with IOSurface-backed frame slots
    let mut backend = MetalBackend::new_metal_encoder(width, height, sample_count, n_buffers);

    // Create VideoToolbox encoder
    let mut encoder = MetalEncoder::new(output, width, height, fps);

    // Uniform staging
    let uniform_alignment: usize = 256;
    let max_objects = scene.objects.len().max(1);
    let uniform_size = std::mem::size_of::<ObjectUniform>();
    let cam_size = std::mem::size_of::<CameraUniform>();
    let mut uniform_staging = vec![0u8; max_objects * uniform_alignment];

    // Frame dedup state
    let mut prev_cam_bytes = vec![0u8; cam_size];
    let mut prev_uniform_bytes = vec![0u8; uniform_staging.len()];
    let mut prev_draw_count: usize = 0;
    let mut first_frame = true;
    let mut dup_count = 0u32;
    let mut render_count = 0usize;

    // Track last rendered slot for dup frame re-encoding
    let mut last_rendered_slot: usize = 0;

    // N-buffering: pending slot queue
    let mut pending: std::collections::VecDeque<usize> = std::collections::VecDeque::new();

    let clear_color = MetalBackend::clear_color(scene);
    let render_start = std::time::Instant::now();
    let mut last_progress = std::time::Instant::now();

    let mut draw_cmds: Vec<(usize, usize)> = Vec::with_capacity(scene.objects.len());

    for frame_idx in 0..total_frames {
        // Progress bar
        print_progress(frame_idx, total_frames, &render_start, &mut last_progress);
        if check_cancelled() { eprintln!("\n  Render interrupted at frame {}/{}", frame_idx, total_frames); break; }

        let time = frame_idx as f32 / fps as f32;
        timeline.evaluate(scene, time);

        // Build camera uniform
        let view_proj = scene.camera.view_projection_matrix(scene.aspect_ratio());
        let cam_uniform = CameraUniform {
            view_proj: view_proj.to_cols_array_2d(),
        };
        let cam_bytes = bytemuck::bytes_of(&cam_uniform);

        // Build draw commands + object uniforms
        draw_cmds.clear();
        for (obj_idx, obj) in scene.objects.iter().enumerate() {
            if obj.material.opacity <= 0.0 {
                continue;
            }
            let slot = draw_cmds.len();
            let byte_offset = slot * uniform_alignment;

            if byte_offset + uniform_size > uniform_staging.len() {
                let new_len = (byte_offset + uniform_size).next_power_of_two();
                uniform_staging.resize(new_len, 0);
                prev_uniform_bytes.resize(new_len, 0);
            }

            let mut material_color = obj.material.color;
            material_color[3] = obj.material.color[3] * obj.material.opacity;

            let uniform = ObjectUniform {
                model: obj.transform.to_matrix().to_cols_array_2d(),
                material_color,
                use_vertex_colors: if obj.material.use_vertex_colors { 1 } else { 0 },
                _pad: [0; 3],
            };
            uniform_staging[byte_offset..byte_offset + uniform_size]
                .copy_from_slice(bytemuck::bytes_of(&uniform));
            draw_cmds.push((obj_idx, slot));
        }

        let total_uniform_bytes = draw_cmds.len() * uniform_alignment;

        // Frame deduplication
        let is_dup = !first_frame
            && draw_cmds.len() == prev_draw_count
            && cam_bytes == &prev_cam_bytes[..]
            && (total_uniform_bytes == 0
                || uniform_staging[..total_uniform_bytes]
                    == prev_uniform_bytes[..total_uniform_bytes]);

        if is_dup {
            // Drain any pending GPU slots before encoding dup
            while let Some(drain_idx) = pending.pop_front() {
                backend.drain_slot_metal(drain_idx);
                encoder.encode_frame(backend.slot_cv_pixel_buffer(drain_idx));
                last_rendered_slot = drain_idx;
            }
            // Re-encode from last rendered slot's IOSurface (still has the data)
            encoder.encode_frame(backend.slot_cv_pixel_buffer(last_rendered_slot));
            dup_count += 1;
            continue;
        }

        let slot_idx = render_count % n;

        // Drain oldest pending slot if all slots are in use
        if pending.len() >= n {
            let drain_idx = pending.pop_front().unwrap();
            backend.drain_slot_metal(drain_idx);
            encoder.encode_frame(backend.slot_cv_pixel_buffer(drain_idx));
            last_rendered_slot = drain_idx;
        }

        // Submit this frame's render work
        backend.submit_frame(
            scene,
            cam_bytes,
            &uniform_staging,
            total_uniform_bytes,
            &draw_cmds,
            clear_color,
            slot_idx,
        );
        pending.push_back(slot_idx);

        // Update dedup state
        prev_cam_bytes.copy_from_slice(cam_bytes);
        if total_uniform_bytes > 0 {
            prev_uniform_bytes[..total_uniform_bytes]
                .copy_from_slice(&uniform_staging[..total_uniform_bytes]);
        }
        prev_draw_count = draw_cmds.len();
        first_frame = false;
        render_count += 1;
    }

    // Drain remaining pending slots
    while let Some(drain_idx) = pending.pop_front() {
        backend.drain_slot_metal(drain_idx);
        encoder.encode_frame(backend.slot_cv_pixel_buffer(drain_idx));
    }

    encoder.finish();

    eprintln!();
    let rendered = total_frames - dup_count;
    eprintln!(
        "  frames: {} rendered, {} duplicates skipped ({:.0}%)",
        rendered,
        dup_count,
        dup_count as f64 / total_frames as f64 * 100.0,
    );
}

fn print_progress(
    frame_idx: u32,
    total_frames: u32,
    render_start: &std::time::Instant,
    last_progress: &mut std::time::Instant,
) {
    if last_progress.elapsed().as_millis() >= 250 || frame_idx == total_frames - 1 {
        let done = frame_idx + 1;
        let elapsed = render_start.elapsed().as_secs_f64();
        let pct = done as f64 / total_frames as f64;
        let fps_now = if elapsed > 0.0 {
            done as f64 / elapsed
        } else {
            0.0
        };
        let eta = if pct > 0.0 {
            elapsed / pct - elapsed
        } else {
            0.0
        };
        let bar_width = 30;
        let filled = (pct * bar_width as f64) as usize;
        let bar: String = "█".repeat(filled) + &"░".repeat(bar_width - filled);
        eprint!(
            "\r  [{}] {:>3.0}% | {}/{} | {:.1}s | ~{:.1}s left | {:.0} fps\x1b[K",
            bar,
            pct * 100.0,
            done,
            total_frames,
            elapsed,
            eta,
            fps_now,
        );
        *last_progress = std::time::Instant::now();
    }
}
