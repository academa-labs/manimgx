use std::io::Write;
use std::process::{Child, Command, Stdio};

#[derive(Debug, Clone, Copy)]
pub enum FfmpegCodec {
    H264VideoToolbox,
    H264Vaapi,
}

pub struct FfmpegEncoder {
    child: Child,
    expected_frame_size: usize,
}

impl FfmpegEncoder {
    pub fn with_pixel_format(
        output_path: &str,
        width: u32,
        height: u32,
        fps: u32,
        codec: FfmpegCodec,
        crf: u32,
        pixel_format: &str,
    ) -> Self {
        let expected_frame_size = match pixel_format {
            "nv12" => (width * height * 3 / 2) as usize,
            _ => (width * height * 4) as usize,
        };

        let mut args = vec![
            "-y".to_string(),
            "-f".to_string(),
            "rawvideo".to_string(),
            "-pixel_format".to_string(),
            pixel_format.to_string(),
            "-video_size".to_string(),
            format!("{}x{}", width, height),
            "-framerate".to_string(),
            fps.to_string(),
        ];

        // NV12: signal BT.709 color space to ffmpeg input
        if pixel_format == "nv12" {
            args.extend([
                "-color_primaries".to_string(),
                "bt709".to_string(),
                "-color_trc".to_string(),
                "bt709".to_string(),
                "-colorspace".to_string(),
                "bt709".to_string(),
            ]);
        }

        // VAAPI needs -vaapi_device before -i
        if matches!(codec, FfmpegCodec::H264Vaapi) {
            args.extend([
                "-vaapi_device".to_string(), "/dev/dri/renderD128".to_string(),
            ]);
        }

        args.extend(["-i".to_string(), "-".to_string()]);

        match codec {
            FfmpegCodec::H264VideoToolbox => {
                args.extend([
                    "-c:v".to_string(),
                    "h264_videotoolbox".to_string(),
                ]);
                // NV12 is already YUV420 semi-planar — no swscale needed
                if pixel_format != "nv12" {
                    args.extend(["-pix_fmt".to_string(), "yuv420p".to_string()]);
                }
                args.extend([
                    "-q:v".to_string(),
                    "65".to_string(),
                    "-allow_sw".to_string(),
                    "0".to_string(),
                ]);
            }
            FfmpegCodec::H264Vaapi => {
                args.extend([
                    "-c:v".to_string(), "h264_vaapi".to_string(),
                ]);
                if pixel_format != "nv12" {
                    args.extend(["-vf".to_string(), "format=nv12,hwupload".to_string()]);
                } else {
                    args.extend(["-vf".to_string(), "hwupload".to_string()]);
                }
                args.extend([
                    "-qp".to_string(), crf.to_string(),
                ]);
            }
        }

        args.push(output_path.to_string());

        let child = Command::new("ffmpeg")
            .args(&args)
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect(
                "Failed to start ffmpeg. Please ensure ffmpeg is installed and available in PATH.\n\
                 Install with: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)",
            );

        log::info!(
            "ffmpeg encoder started ({:?}): {}x{} @ {} fps -> {}",
            codec,
            width,
            height,
            fps,
            output_path
        );

        Self {
            child,
            expected_frame_size,
        }
    }

    pub fn write_frame(&mut self, pixels: &[u8]) {
        assert_eq!(
            pixels.len(),
            self.expected_frame_size,
            "Frame size mismatch: expected {} bytes, got {}",
            self.expected_frame_size,
            pixels.len()
        );

        if let Some(stdin) = self.child.stdin.as_mut() {
            stdin
                .write_all(pixels)
                .expect("Failed to write frame to ffmpeg");
        }
    }

    pub fn finish(mut self) {
        // Close stdin to signal EOF to ffmpeg
        drop(self.child.stdin.take());
        let status = self.child.wait().expect("Failed to wait for ffmpeg");
        if !status.success() {
            log::error!("ffmpeg exited with status: {}", status);
        } else {
            log::info!("ffmpeg encoding completed successfully");
        }
    }
}

