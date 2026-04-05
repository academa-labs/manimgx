#[allow(non_upper_case_globals, non_camel_case_types, non_snake_case, dead_code)]
mod bindings {
    include!(concat!(env!("OUT_DIR"), "/x264_bindings.rs"));
}
use bindings::*;

use std::sync::mpsc::{channel, Sender};
use std::thread::{self, JoinHandle};

/// Message sent from the render loop to the encoder thread.
pub enum X264FrameMsg {
    /// A new frame: pointer into a pool NV12 buffer.
    Frame {
        ptr: *const u8,
        len: usize,
        pts: i64,
        buf_idx: usize,
    },
    /// Duplicate frame: re-encode from the scratch buffer.
    Dup { pts: i64 },
    /// Flush delayed frames and shut down.
    Flush,
}

// SAFETY: ptr points to a pinned buffer (MTLBuffer or Vec<u8>) in shared storage.
// The buffer remains valid until the encoder thread sends buf_idx back
// via release_tx, at which point the pool reclaims it. The main thread
// only reuses pool buffers after they are released.
unsafe impl Send for X264FrameMsg {}

/// In-process x264 encoder. Spawns an encoder thread that receives NV12
/// frames via an unbounded channel and muxes directly to MP4.
pub struct X264Writer {
    sender: Sender<X264FrameMsg>,
    handle: Option<JoinHandle<()>>,
}

impl X264Writer {
    pub fn new(
        output: &str,
        width: u32,
        height: u32,
        fps: u32,
        preset: &str,
        crf: u32,
        release_tx: Sender<usize>,
        muxer: &str,
    ) -> Self {
        use manimgx_core::mp4_muxer::MuxerStrategy;
        let strategy = match muxer {
            "ram" => MuxerStrategy::Ram,
            "fmp4" => MuxerStrategy::Fmp4,
            _ => MuxerStrategy::Disk,
        };

        let output_owned = output.to_string();
        let width_i = width as i32;
        let height_i = height as i32;
        let fps_i = fps as i32;
        let crf_f = crf as f32;
        let preset_owned = preset.to_string();

        // Unbounded channel: elastic pool provides backpressure instead
        let (sender, receiver) = channel::<X264FrameMsg>();

        let handle = thread::spawn(move || {
            unsafe {
                encoder_thread_main(
                    &receiver,
                    &output_owned,
                    width_i,
                    height_i,
                    fps_i,
                    crf_f,
                    &preset_owned,
                    &release_tx,
                    strategy,
                );
            }
        });

        Self {
            sender,
            handle: Some(handle),
        }
    }

    /// Send a frame to the encoder thread (zero-copy from pool buffer).
    pub fn send(&self, msg: X264FrameMsg) {
        self.sender.send(msg).expect("x264 encoder thread died");
    }

    /// Flush encoder, join thread. MP4 is finalized in the encoder thread.
    pub fn finish(mut self) {
        let _ = self.sender.send(X264FrameMsg::Flush);
        if let Some(handle) = self.handle.take() {
            handle.join().expect("x264 encoder thread panicked");
        }
    }
}

/// Encoder thread main loop. Runs entirely on a dedicated thread.
///
/// SAFETY: All x264 FFI calls happen here. x264 copies input plane data
/// internally via plane_copy at the start of x264_encoder_encode, so the
/// pool buffer is safe to release after the call returns. No zerolatency
/// tune needed — frame-level threading is safe with the elastic pool.
unsafe fn encoder_thread_main(
    receiver: &std::sync::mpsc::Receiver<X264FrameMsg>,
    output_path: &str,
    width: i32,
    height: i32,
    fps: i32,
    crf: f32,
    preset: &str,
    release_tx: &Sender<usize>,
    muxer_strategy: manimgx_core::mp4_muxer::MuxerStrategy,
) {
    // 1. Configure x264 params (no tune — frame-level threading for speed)
    let mut param: x264_param_t = std::mem::zeroed();

    let preset_cstr = std::ffi::CString::new(preset).unwrap();
    let ret = x264_param_default_preset(
        &mut param,
        preset_cstr.as_ptr(),
        std::ptr::null(),
    );
    assert!(ret == 0, "x264_param_default_preset failed");

    param.i_width = width;
    param.i_height = height;
    param.i_csp = X264_CSP_NV12 as i32;
    param.i_fps_num = fps as u32;
    param.i_fps_den = 1;
    param.i_timebase_num = 1;
    param.i_timebase_den = fps as u32;
    param.b_repeat_headers = 1;
    param.b_annexb = 1;
    param.rc.f_rf_constant = crf;
    param.vui.i_sar_width = 1;
    param.vui.i_sar_height = 1;
    param.i_log_level = X264_LOG_NONE;

    let profile_cstr = c"high";
    let ret = x264_param_apply_profile(&mut param, profile_cstr.as_ptr());
    assert!(ret == 0, "x264_param_apply_profile failed");

    // 2. Open encoder
    // x264_encoder_open is a version-mangled macro; use the actual symbol
    let encoder = x264_encoder_open_165(&mut param);
    assert!(!encoder.is_null(), "x264_encoder_open failed");

    // 3. Init MP4 muxer
    use manimgx_core::mp4_muxer::Mp4Muxer;
    let mut muxer = Mp4Muxer::new(output_path, width as u32, height as u32, fps as f64, muxer_strategy)
        .expect("Failed to create MP4 muxer");
    // 4. Allocate dup scratch buffer (W*H*3/2 bytes for NV12)
    let nv12_size = (width * height * 3 / 2) as usize;
    let mut dup_scratch = vec![0u8; nv12_size];

    // 5. Init picture struct once
    let mut pic: x264_picture_t = std::mem::zeroed();
    x264_picture_init(&mut pic);
    pic.img.i_csp = X264_CSP_NV12 as i32;
    pic.img.i_plane = 2;
    // Strides: Y plane = width, UV plane = width (interleaved U/V)
    pic.img.i_stride[0] = width;
    pic.img.i_stride[1] = width;

    let mut pic_out: x264_picture_t = std::mem::zeroed();

    // Helper: pass raw NAL slices directly to muxer (zero Annex B roundtrip)
    macro_rules! mux_nals {
        ($frame_size:expr, $pp_nal:expr, $i_nal:expr, $pic_out:expr) => {
            if $frame_size > 0 {
                let is_keyframe = $pic_out.b_keyframe != 0;

                // Build slice of raw NAL payloads, stripping Annex B start codes
                let mut nal_slices: Vec<&[u8]> = Vec::with_capacity($i_nal as usize);
                for i in 0..$i_nal as isize {
                    let nal = &*$pp_nal.offset(i);
                    let data = std::slice::from_raw_parts(nal.p_payload, nal.i_payload as usize);
                    // x264 NALs include Annex B start code; strip to get raw NAL unit
                    let raw = if data.len() > 4
                        && data[0] == 0 && data[1] == 0 && data[2] == 0 && data[3] == 1
                    {
                        &data[4..]
                    } else if data.len() > 3
                        && data[0] == 0 && data[1] == 0 && data[2] == 1
                    {
                        &data[3..]
                    } else {
                        data
                    };
                    nal_slices.push(raw);
                }

                let pts_secs = $pic_out.i_pts as f64 / fps as f64;
                let dts_secs = $pic_out.i_dts as f64 / fps as f64;
                muxer.write_video_nals(pts_secs, dts_secs, &nal_slices, is_keyframe)
                    .expect("Failed to write frame to MP4 muxer");
            }
        };
    }

    // 6. Encode loop
    loop {
        let msg = match receiver.recv() {
            Ok(msg) => msg,
            Err(_) => break, // channel closed
        };

        match msg {
            X264FrameMsg::Frame { ptr, len, pts, buf_idx } => {
                debug_assert_eq!(len, nv12_size);

                // Set plane pointers into the pool buffer
                pic.img.plane[0] = ptr as *mut u8;
                pic.img.plane[1] = ptr.add((width * height) as usize) as *mut u8;
                pic.i_pts = pts;

                let mut pp_nal: *mut x264_nal_t = std::ptr::null_mut();
                let mut i_nal: i32 = 0;

                let frame_size = x264_encoder_encode(
                    encoder,
                    &mut pp_nal,
                    &mut i_nal,
                    &mut pic,
                    &mut pic_out,
                );
                assert!(frame_size >= 0, "x264_encoder_encode failed");

                // Memcpy NV12 data to dup scratch BEFORE releasing buffer
                // (so we have a copy for potential Dup frames)
                std::ptr::copy_nonoverlapping(ptr, dup_scratch.as_mut_ptr(), nv12_size);

                // Release pool buffer back to the main thread
                let _ = release_tx.send(buf_idx);

                mux_nals!(frame_size, pp_nal, i_nal, pic_out);
            }

            X264FrameMsg::Dup { pts } => {
                // Encode from the dup scratch buffer (not from pool buffer)
                pic.img.plane[0] = dup_scratch.as_ptr() as *mut u8;
                pic.img.plane[1] = dup_scratch.as_ptr().add((width * height) as usize) as *mut u8;
                pic.i_pts = pts;

                let mut pp_nal: *mut x264_nal_t = std::ptr::null_mut();
                let mut i_nal: i32 = 0;

                let frame_size = x264_encoder_encode(
                    encoder,
                    &mut pp_nal,
                    &mut i_nal,
                    &mut pic,
                    &mut pic_out,
                );
                assert!(frame_size >= 0, "x264_encoder_encode (dup) failed");

                mux_nals!(frame_size, pp_nal, i_nal, pic_out);
            }

            X264FrameMsg::Flush => {
                // Drain delayed frames
                loop {
                    let delayed = x264_encoder_delayed_frames(encoder);
                    if delayed == 0 {
                        break;
                    }

                    let mut pp_nal: *mut x264_nal_t = std::ptr::null_mut();
                    let mut i_nal: i32 = 0;

                    let frame_size = x264_encoder_encode(
                        encoder,
                        &mut pp_nal,
                        &mut i_nal,
                        std::ptr::null_mut(),
                        &mut pic_out,
                    );
                    if frame_size < 0 {
                        break;
                    }

                    mux_nals!(frame_size, pp_nal, i_nal, pic_out);
                }

                x264_encoder_close(encoder);
                break;
            }
        }
    }

    // Finalize MP4 (writes moov atom, applies fast-start)
    muxer.finish().expect("Failed to finalize MP4 file");
}
