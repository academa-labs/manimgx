#![cfg(target_os = "macos")]

mod backend;
pub(crate) mod metal_encoder;

#[cfg(not(feature = "time_profile"))]
mod render_loop_x264;
#[cfg(feature = "time_profile")]
#[path = "render_loop_x264_profile.rs"]
mod render_loop_x264;
#[cfg(not(feature = "time_profile"))]
mod render_loop_metal;
#[cfg(feature = "time_profile")]
#[path = "render_loop_metal_profile.rs"]
mod render_loop_metal;

pub use backend::MetalBackend;
pub use render_loop_metal::render_video_metal;
pub use render_loop_x264::render_video_x264;
