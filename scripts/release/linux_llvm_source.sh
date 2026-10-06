#!/bin/bash
# Temporary cold-build measurement of the complete corrected LLVM dependency.
set -euo pipefail
ulimit -c 0
input=$(realpath "$1")
project=$(realpath "$2")
mkdir -p "$3"
output=$(realpath "$3")
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work=$(mktemp -d)
cleanup() {
  if [ -n "${monitor-}" ]; then kill "$monitor" 2>/dev/null || true; fi
  du -sk "$work" >> "$output/disk-kib.log"
  if [ -f /sys/fs/cgroup/memory.peak ]; then cat /sys/fs/cgroup/memory.peak > "$output/cgroup-memory-peak-bytes.txt"; fi
  rm -rf "$work"
}
trap cleanup EXIT
export MANIMGX_SOURCES="$output/sources"
export CARGO_TARGET_DIR="$work/fetch-target"
llvm_sha256=4633a23617fa31a3ea51242586ea7fb1da7140e426bd62fc164261fe036aa142
set -x
dnf -q -y install llvm llvm-devel llvm-static libxml2-devel time
python=/opt/python/cp313-cp313/bin/python
"$python" -m pip -q install --root-user-action=ignore cmake ninja
export PATH="/opt/python/cp313-cp313/bin:$PATH"
OUT_DIR="$work" cargo run --quiet --locked --manifest-path "$root/rust/Cargo.toml" \
  --package fetch --bin fetch-file -- \
  https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/llvm-project-21.1.8.src.tar.xz \
  "$llvm_sha256"
tar -xJf "$work/$llvm_sha256" -C "$work"
source="$work/llvm-project-21.1.8.src"
cp "$root/scripts/release/llvm/destination-class.patch" "$output/"
patch -d "$source" -p1 < "$output/destination-class.patch"
cp "$input/default-dump/bitcode/cs5_variant0-after.bc" "$output/optimized.bc"
printf '%s  %s\n' 211aed8343ed48be225fde8f01b577f23dd593217eb75ed0c914fa2305034ec7 "$output/optimized.bc" | sha256sum --check
rpm -qa | sort > "$output/rpm-packages.txt"
c++ --version > "$output/cxx-version.txt"
(
  while sleep 5; do
    du -sk "$work" >> "$output/disk-kib.log"
  done
) &
monitor=$!
# Native alone is what this driver executes. RTTI matches Mesa; compression/XML
# readers are unused by the in-memory JIT. No SDK LLVM objects enter this build.
cmake -S "$source/llvm" -B "$work/llvm-build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DLLVM_DEFAULT_TARGET_TRIPLE="$(llvm-config --host-target)" \
  -DLLVM_TARGETS_TO_BUILD=Native -DLLVM_ENABLE_RTTI=ON \
  -DLLVM_ENABLE_ASSERTIONS=OFF -DLLVM_BUILD_LLVM_DYLIB=OFF \
  -DLLVM_LINK_LLVM_DYLIB=OFF -DLLVM_BUILD_TOOLS=OFF \
  -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF \
  -DLLVM_ENABLE_ZLIB=OFF -DLLVM_ENABLE_ZSTD=OFF -DLLVM_ENABLE_LIBXML2=OFF
cp "$work/llvm-build/CMakeCache.txt" "$output/"
/usr/bin/time -v -o "$output/llvm-build-time.txt" \
  timeout --kill-after=10s 1800s cmake --build "$work/llvm-build" --parallel "$(nproc)"
/usr/bin/time -v -o "$output/llvm-tools-time.txt" \
  timeout --kill-after=10s 300s cmake --build "$work/llvm-build" --parallel "$(nproc)" --target llc opt llvm-config
export PATH="$work/llvm-build/bin:$PATH"
test "$(command -v llvm-config)" = "$work/llvm-build/bin/llvm-config"
llvm-config --version --prefix --cxxflags > "$output/llvm-config.txt"
features=+64bit,+sse,+sse2,+sse3,+ssse3,+sse4.1,+sse4.2,+avx,+f16c,+fma,+avx2,+avx512f,+avx512cd,+avx512bw,+avx512dq,+avx512vl,+avx512vbmi
target=(-mtriple=x86_64-redhat-linux-gnu -mcpu=znver5 -mattr="$features" -code-model=large -relocation-model=static)
opt -passes=verify -disable-output "$output/optimized.bc"
for level in 1 2; do
  llc "${target[@]}" -O"$level" -verify-machineinstrs "$output/optimized.bc" \
    -o "$output/O$level.s" > "$output/O$level-verify.log" 2>&1
done
subregister="$source/llvm/test/CodeGen/X86/splitkit-remat-broken-subreg-constraint.mir"
regression=(-mtriple=x86_64-- -run-pass=greedy -verify-machineinstrs -verify-regalloc -stress-regalloc=2 "$subregister")
/usr/bin/llc "${regression[@]}" -o "$output/installed-subregister.mir"
llc "${regression[@]}" -o "$output/patched-subregister.mir"
cmp "$output/installed-subregister.mir" "$output/patched-subregister.mir"
"$python" "$root/scripts/release/linux_mesa.py" prepare "$project" "$output/patched-mesa"
mkdir "$work/mesa-tmp"
/usr/bin/time -v -o "$output/mesa-build-time.txt" \
  env TMPDIR="$work/mesa-tmp" sh "$project/scripts/release/build_lavapipe.diagnostic.sh" "$output/driver"
sha256sum "$output/driver/libvulkan_lvp.so" "$output/destination-class.patch" "$output/optimized.bc" > "$output/hashes.txt"
