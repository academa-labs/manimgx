use std::pin::pin;
use std::task::{Context, Poll, Waker};

pub struct GpuContext {
    pub device: wgpu::Device,
    pub queue: wgpu::Queue,
}

/// Poll a future that is expected to resolve synchronously (wgpu native).
fn block_on<F: std::future::Future>(future: F) -> F::Output {
    let waker = Waker::noop();
    let mut cx = Context::from_waker(&waker);
    let mut future = pin!(future);
    match future.as_mut().poll(&mut cx) {
        Poll::Ready(v) => v,
        Poll::Pending => unreachable!("wgpu futures resolve synchronously on native"),
    }
}

impl Default for GpuContext {
    fn default() -> Self {
        Self::new()
    }
}

impl GpuContext {
    pub fn new() -> Self {
        Self::with_features(wgpu::Features::empty())
    }

    pub fn with_features(features: wgpu::Features) -> Self {
        block_on(Self::init(features))
    }

    async fn init(features: wgpu::Features) -> Self {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::all(),
            ..Default::default()
        });

        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: None,
                force_fallback_adapter: false,
            })
            .await
            .expect("Failed to find a suitable GPU adapter. Ensure you have a GPU with Vulkan/Metal/DX12 support.");

        let (device, queue) = adapter
            .request_device(
                &wgpu::DeviceDescriptor {
                    label: Some("manimgx-device"),
                    required_features: features,
                    required_limits: wgpu::Limits::default(),
                    ..Default::default()
                },
                None,
            )
            .await
            .expect("Failed to create GPU device");

        log::info!("GPU initialized: {:?}", adapter.get_info().name);

        Self { device, queue }
    }
}
