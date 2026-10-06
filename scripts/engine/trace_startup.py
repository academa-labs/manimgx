"""Temporary Windows phase attribution; never used by an ordinary product build."""

import difflib
import hashlib
import json
import subprocess
import tarfile
import tomllib
from pathlib import Path


def main() -> None:
    root = Path.cwd()
    rust = root / "rust"
    locked = (rust / "Cargo.lock").read_text(encoding="utf-8")
    lock = tomllib.loads(locked)
    package = next(p for p in lock["package"] if p["name"] == "wgpu-hal")
    assert package["version"] == "30.0.1", package
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--locked", "--format-version", "1"],
            cwd=rust,
            text=True,
        )
    )
    manifest = next(
        Path(p["manifest_path"])
        for p in metadata["packages"]
        if p["name"] == "wgpu-hal" and p["version"] == package["version"]
    )
    source = manifest.parent
    archive = source.parents[2] / "cache" / source.parent.name / f"{source.name}.crate"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest == package["checksum"], (archive, digest, package["checksum"])
    target = root / "startup-hal"
    target.mkdir()
    with tarfile.open(archive) as packed:
        packed.extractall(target, filter="data")
    hal = target / source.name / "src" / "dx12"
    changes: dict[Path, tuple[str, str]] = {}

    def edit(path: Path, old: str, new: str) -> None:
        before, current = changes.get(
            path, (text := path.read_text(encoding="utf-8"), text)
        )
        assert current.count(old) == 1, (path, old, current.count(old))
        changes[path] = before, current.replace(old, new)

    # The cache, compilation options, shader text and pipeline descriptors are unchanged.
    # Each scoped timer ends before the following stage begins, including early returns.
    device = hal / "device.rs"
    timer = """
pub(super) struct StartupTimer(&'static str, String, Instant);
impl StartupTimer {
    pub(super) fn new(phase: &'static str, label: &str) -> Self {
        Self(phase, label.to_owned(), Instant::now())
    }
}
impl Drop for StartupTimer {
    fn drop(&mut self) {
        eprintln!("native-phase\\t{}\\t{}\\t{}\\t{:.9}",
            std::process::id(), self.0, self.1, self.2.elapsed().as_secs_f64());
    }
}
"""
    text = device.read_text(encoding="utf-8")
    changes[device] = text, text + timer
    edit(
        device,
        "        let stage_bit = auxil::map_naga_stage(naga_stage);",
        '        let _trace = StartupTimer::new("shader-load", stage.entry_point);\n'
        "        let stage_bit = auxil::map_naga_stage(naga_stage);",
    )
    edit(
        device,
        '            profiling::scope!("ID3D12Device::CreateComputePipelineState");',
        '            let _trace = StartupTimer::new("compute-pso", desc.label.unwrap_or(""));\n'
        '            profiling::scope!("ID3D12Device::CreateComputePipelineState");',
    )
    edit(
        device,
        '                    profiling::scope!("ID3D12Device2::CreatePipelineState");',
        '                    let _trace = StartupTimer::new("graphics-pso", desc.label.unwrap_or(""));\n'
        '                    profiling::scope!("ID3D12Device2::CreatePipelineState");',
    )
    edit(
        device,
        "                    let desc = stream_desc.to_graphics_pipeline_descriptor();",
        '                    let _trace = StartupTimer::new("graphics-pso", desc.label.unwrap_or(""));\n'
        "                    let desc = stream_desc.to_graphics_pipeline_descriptor();",
    )
    compilation = hal / "shader_compilation.rs"
    edit(
        compilation,
        '    profiling::scope!("compile_dxc");',
        '    let label = String::from(raw_ep);\n    profiling::scope!("compile_dxc");',
    )
    edit(
        compilation,
        "    let compile_res: Dxc::IDxcResult =",
        '    let trace = super::device::StartupTimer::new("dxc", &label);\n'
        "    let compile_res: Dxc::IDxcResult =",
    )
    edit(
        compilation,
        "    drop(compile_args);",
        "    drop(trace);\n    drop(compile_args);",
    )

    render = rust / "engine" / "src" / "render.rs"
    edit(
        render,
        "        self.with_working_set(&gpu.device.limits(), frames, |player| player.encode_frame(gpu, frames))",
        "        let trace = std::time::Instant::now();\n"
        "        let result = self.with_working_set(&gpu.device.limits(), frames, |player| player.encode_frame(gpu, frames));\n"
        '        eprintln!("native-phase\\t{}\\tencode\\tframe\\t{:.9}", std::process::id(), trace.elapsed().as_secs_f64());\n'
        "        result",
    )
    edit(
        render,
        '        self.targets.as_ref().expect("targets").readback.slice(..).map_async(wgpu::MapMode::Read, |_| {});',
        "        let trace = std::time::Instant::now();\n"
        '        self.targets.as_ref().expect("targets").readback.slice(..).map_async(wgpu::MapMode::Read, |_| {});',
    )
    edit(
        render,
        "        gpu.device.poll(wgpu::PollType::wait_indefinitely()).map_err(|e| e.to_string())?;",
        "        gpu.device.poll(wgpu::PollType::wait_indefinitely()).map_err(|e| e.to_string())?;\n"
        '        eprintln!("native-phase\\t{}\\twait-map\\tframe\\t{:.9}", std::process::id(), trace.elapsed().as_secs_f64());',
    )
    python = rust / "engine" / "src" / "python.rs"
    edit(
        python,
        "                    gpu.queue.submit(Some(encoder.finish()));",
        "                    let trace = std::time::Instant::now();\n"
        "                    let command = encoder.finish();\n"
        '                    eprintln!("native-phase\\t{}\\tfinish\\tframe\\t{:.9}", std::process::id(), trace.elapsed().as_secs_f64());\n'
        "                    let trace = std::time::Instant::now();\n"
        "                    gpu.queue.submit(Some(command));\n"
        '                    eprintln!("native-phase\\t{}\\tsubmit\\tframe\\t{:.9}", std::process::id(), trace.elapsed().as_secs_f64());',
    )
    manifest = rust / "Cargo.toml"
    before = manifest.read_text(encoding="utf-8")
    assert "[patch.crates-io]" not in before
    changes[manifest] = (
        before,
        (
            before
            + f'\n[patch.crates-io]\nwgpu-hal = {{ path = "../startup-hal/{source.name}" }}\n'
        ),
    )
    patch = ""
    for path, (before, after) in changes.items():
        name = path.relative_to(root).as_posix()
        patch += "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )
        path.write_text(after, encoding="utf-8")
    (root / "startup-trace.patch").write_text(patch, encoding="utf-8")
    registered = (
        f'name = "wgpu-hal"\nversion = "{package["version"]}"\n'
        f'source = "{package["source"]}"\nchecksum = "{package["checksum"]}"\n'
    )
    assert locked.count(registered) == 1
    (rust / "Cargo.lock").write_text(
        locked.replace(
            registered, f'name = "wgpu-hal"\nversion = "{package["version"]}"\n'
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["cargo", "metadata", "--locked", "--offline", "--format-version", "1"],
        cwd=rust,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    package.pop("source")
    package.pop("checksum")
    assert tomllib.loads((rust / "Cargo.lock").read_text(encoding="utf-8")) == lock
    (root / "startup-trace-Cargo.lock").write_bytes((rust / "Cargo.lock").read_bytes())
    (root / "startup-trace.json").write_text(
        json.dumps(
            {
                "crate": archive.name,
                "crate_sha256": digest,
                "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                "lock_sha256": hashlib.sha256(
                    (rust / "Cargo.lock").read_bytes()
                ).hexdigest(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
