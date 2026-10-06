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
  for log in "$work"/mesa-tmp/*/mesa-build/meson-logs/meson-log.txt; do
    if [ -f "$log" ]; then cp "$log" "$output/meson-log.txt"; fi
  done
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
    du -sk "$work" >> "$output/disk-kib.log" 2>/dev/null || true
  done
) &
monitor=$!
# Native alone is what this driver executes. RTTI matches Mesa; compression/XML
# readers are unused by the in-memory JIT. No SDK LLVM objects enter this build.
cmake -S "$source/llvm" -B "$work/llvm-build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DCMAKE_INSTALL_PREFIX="$work/llvm-prefix" \
  -DLLVM_DEFAULT_TARGET_TRIPLE="$(llvm-config --host-target)" \
  -DLLVM_TARGETS_TO_BUILD=Native -DLLVM_ENABLE_RTTI=ON \
  -DLLVM_ENABLE_ASSERTIONS=OFF -DLLVM_BUILD_LLVM_DYLIB=OFF \
  -DLLVM_LINK_LLVM_DYLIB=OFF -DLLVM_BUILD_TOOLS=ON \
  -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF \
  -DLLVM_ENABLE_ZLIB=OFF -DLLVM_ENABLE_ZSTD=OFF -DLLVM_ENABLE_LIBXML2=OFF
cp "$work/llvm-build/CMakeCache.txt" "$output/"
cp "$work/llvm-build/tools/llvm-config/LibraryDependencies.inc" "$output/"
# Meson's llvm-config --shared-mode query checks every configured library, even
# when linking a subset. Use LLVM's complete native library distribution target.
targets=(llvm-libraries llvm-config llc opt)
ninja -C "$work/llvm-build" -n all > "$output/llvm-all-plan.txt"
ninja -C "$work/llvm-build" -n "${targets[@]}" > "$output/llvm-build-plan.txt"
/usr/bin/time -v -o "$output/llvm-build-time.txt" \
  timeout --kill-after=10s 3600s cmake --build "$work/llvm-build" --parallel "$(nproc)" --target "${targets[@]}"
cmake --build "$work/llvm-build" --parallel "$(nproc)" --target \
  install-llvm-libraries install-llvm-headers install-llvm-config install-llc install-opt
# Retain the reusable compiler before downstream verification or Mesa can fail.
(
  cd "$work/llvm-prefix"
  find . -type f -print0 | sort -z | xargs -0 sha256sum
) > "$output/llvm-files.sha256"
tar -czf "$output/llvm-toolchain.tar.gz" -C "$work" llvm-prefix
(
  cd "$output"
  sha256sum llvm-toolchain.tar.gz CMakeCache.txt destination-class.patch \
    sources/llvm-project-21.1.8.src.tar.xz
) > "$output/llvm-inputs.sha256"
export PATH="$work/llvm-prefix/bin:$PATH"
test "$(command -v llvm-config)" = "$work/llvm-prefix/bin/llvm-config"
llvm-config --version --prefix --cxxflags > "$output/llvm-config.txt"
llvm-config --shared-mode > "$output/llvm-shared-mode.txt"
llvm-config --link-static --libfiles bitwriter engine mcdisassembler mcjit core \
  executionengine scalaropts transformutils instcombine coroutines native lto \
  > "$output/llvm-mesa-libraries.txt"
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
# The outer cleanup retains Meson's failure log before removing its scratch tree.
sed -i 's/trap '\''rm -rf "$work"'\'' EXIT HUP INT TERM/trap : EXIT HUP INT TERM/' \
  "$project/scripts/release/build_lavapipe.diagnostic.sh"
grep -qx 'trap : EXIT HUP INT TERM' "$project/scripts/release/build_lavapipe.diagnostic.sh"
cat >> "$project/scripts/release/build_lavapipe.diagnostic.sh" <<'PROVENANCE'
cp mesa-build/meson-logs/meson-log.txt "$out/meson-log.txt"
ninja -C mesa-build -t commands src/gallium/targets/lavapipe/libvulkan_lvp.so > "$out/build-commands.txt"
PROVENANCE
mkdir "$work/mesa-tmp"
/usr/bin/time -v -o "$output/mesa-build-time.txt" \
  env TMPDIR="$work/mesa-tmp" sh "$project/scripts/release/build_lavapipe.diagnostic.sh" "$output/driver"
sha256sum "$output/driver/libvulkan_lvp.so" "$output/destination-class.patch" "$output/optimized.bc" > "$output/hashes.txt"
