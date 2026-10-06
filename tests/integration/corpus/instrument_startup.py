"""Temporary Windows startup experiment: instrument a disposable native build only.

The default wheel never imports this module or includes the generated Rust module.
Remove this script and startup-native.yaml after first-execution costs are attributed.
"""

import argparse
from pathlib import Path

TIMING = r"""
//! Temporary startup experiment; generated only by the manual diagnostic workflow.

pub(crate) fn time<T>(label: &str, action: impl FnOnce() -> T) -> T {
    let start = std::time::Instant::now();
    let value = action();
    eprintln!("NATIVE_TIMING\t{}\t{}\t{:.9}", std::process::id(), label, start.elapsed().as_secs_f64());
    value
}

pub(crate) trait TimedDevice {
    fn timed_compute_pipeline(&self, descriptor: &wgpu::ComputePipelineDescriptor<'_>) -> wgpu::ComputePipeline;
    fn timed_render_pipeline(&self, descriptor: &wgpu::RenderPipelineDescriptor<'_>) -> wgpu::RenderPipeline;
}

impl TimedDevice for wgpu::Device {
    fn timed_compute_pipeline(&self, descriptor: &wgpu::ComputePipelineDescriptor<'_>) -> wgpu::ComputePipeline {
        time(&format!("pipeline.compute.{}", descriptor.label.unwrap_or("unnamed")), || self.create_compute_pipeline(descriptor))
    }

    fn timed_render_pipeline(&self, descriptor: &wgpu::RenderPipelineDescriptor<'_>) -> wgpu::RenderPipeline {
        time(&format!("pipeline.render.{}", descriptor.label.unwrap_or("unnamed")), || self.create_render_pipeline(descriptor))
    }
}

pub(crate) fn flush(device: &wgpu::Device, queue: &wgpu::Queue, encoder: &mut wgpu::CommandEncoder, label: &str) {
    if std::env::var("MANIMGX_DIAGNOSTIC_SPLIT").as_deref() == Ok("1") {
        time(label, || {
            let pending = std::mem::replace(encoder, device.create_command_encoder(&Default::default()));
            queue.submit(Some(pending.finish()));
            device.poll(wgpu::PollType::wait_indefinitely()).expect("diagnostic pass completed");
        });
    }
}
"""


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(
            f"{path}: expected exactly one instrumentation boundary: {old}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def instrument(root: Path) -> None:
    for path in root.glob("*.rs"):
        text = path.read_text(encoding="utf-8")
        changed = text.replace(
            ".create_compute_pipeline(", ".timed_compute_pipeline("
        ).replace(".create_render_pipeline(", ".timed_render_pipeline(")
        if changed != text:
            # The import follows module documentation, keeping inner comments valid.
            lines = changed.splitlines(keepends=True)
            at = next(i for i, line in enumerate(lines) if not line.startswith("//!"))
            lines.insert(at, "use crate::startup_timing::TimedDevice as _;\n")
            path.write_text("".join(lines), encoding="utf-8")
    (root / "startup_timing.rs").write_text(TIMING, encoding="utf-8")
    with (root / "lib.rs").open("a", encoding="utf-8") as stream:
        stream.write('\n#[cfg(feature = "render")]\nmod startup_timing;\n')

    python = root / "python.rs"
    replace(
        python,
        "self.encode(gpu, &frames)?",
        'crate::startup_timing::time("encode", || self.encode(gpu, &frames))?',
    )
    replace(
        python,
        "gpu.queue.submit(Some(encoder.finish()));",
        'let command = crate::startup_timing::time("finish", || encoder.finish());\n'
        '                    crate::startup_timing::time("submit", || gpu.queue.submit(Some(command)));',
    )
    replace(
        python,
        "self.map_pixels(gpu)?;",
        'crate::startup_timing::time("wait_map", || self.map_pixels(gpu))?;',
    )
    vector = root / "vector.rs"
    replace(
        vector,
        "self.composite(device, key, plan.crossings)",
        'self.composite(device, key, plan.crossings || std::env::var("MANIMGX_DIAGNOSTIC_EAGER").as_deref() == Ok("1"))',
    )
    replace(
        vector,
        "pass.dispatch_workgroups(slots.min(65535), slots.div_ceil(65535), 1);\n        }",
        "pass.dispatch_workgroups(slots.min(65535), slots.div_ceil(65535), 1);\n"
        "            drop(pass);\n"
        '            crate::startup_timing::flush(device, queue, encoder, "execute.flatten");\n        }',
    )
    replace(
        vector,
        "accumulate(encoder, &read);",
        "accumulate(encoder, &read);\n"
        '            crate::startup_timing::flush(device, queue, encoder, "execute.coverage");',
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("rust/engine/src"))
    instrument(parser.parse_args().root)
