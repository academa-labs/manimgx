#!/bin/bash
# Temporary compiler experiment: one rebuilt object, with an unmodified rebuild control.
set -euo pipefail
ulimit -c 0
input=$(realpath "$1")
mkdir -p "$2"
output=$(realpath "$2")
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$output"
cp "$input/default-dump/bitcode/cs5_variant0-after.bc" optimized.bc
printf '%s\n' '211aed8343ed48be225fde8f01b577f23dd593217eb75ed0c914fa2305034ec7  optimized.bc' | sha256sum --check

set -x
dnf -q -y install llvm llvm-devel llvm-static libxml2-devel
test "$(llvm-config --version)" = 21.1.8
llvm-config --version --cxxflags --ldflags --assertion-mode > compiler-config.txt
rpm -qa | sort > rpm-packages.txt
mkdir -p upstream/llvm/lib/CodeGen upstream/llvm/tools/llc
while read -r digest path; do
  curl --proto '=https' --tlsv1.2 --silent --show-error --fail \
    "https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-21.1.8/$path" \
    -o "upstream/$path"
  printf '%s  %s\n' "$digest" "upstream/$path" | sha256sum --check
done <<'SOURCES'
a2f10c4adbbdffe5d22b54dd79edac37942225d6e68b69e0d268e876813d6dcc llvm/lib/CodeGen/SplitKit.cpp
933d06332f1bb109b95863e72548c8b06e13574112447876cf19b00c87b72f7f llvm/lib/CodeGen/SplitKit.h
12f474e698c300338f89ade075f6197c94171f891f0f8e5835d239b5428c8081 llvm/tools/llc/llc.cpp
ad73b8f66d166f1e4d167426da94c4ed6177d4382bfceebf1e62bc59c7eea141 llvm/tools/llc/NewPMDriver.cpp
7e9b588f3f375d3df72406ddd9404cb4a48b0149cb03be675d75f757bca297ed llvm/tools/llc/NewPMDriver.h
SOURCES
cp -r upstream patched
cp "$root/scripts/release/llvm/destination-class.patch" .
patch -d patched -p1 < destination-class.patch
trap 'rm -f upstream/llc patched/llc original-CodeGen.a' EXIT

archive=$(llvm-config --libdir)/libLLVMCodeGen.a
llvm-ar t "$archive" > codegen-members.txt
test "$(grep -cx 'SplitKit.cpp.o' codegen-members.txt)" -eq 1
cp "$archive" original-CodeGen.a
# All builds use the SDK's ABI flags, installed generated headers and static dependencies.
# Rebuilding the unmodified object first detects any mismatch in that boundary.
read -r -a cxxflags <<< "$(llvm-config --cxxflags)"
read -r -a ldflags <<< "$(llvm-config --link-static --ldflags --libs all --system-libs | tr '\n' ' ')"
c++ "${cxxflags[@]}" -O2 -fPIC -c upstream/llvm/tools/llc/llc.cpp -o llc.o
c++ "${cxxflags[@]}" -O2 -fPIC -c upstream/llvm/tools/llc/NewPMDriver.cpp -o NewPMDriver.o
features=+64bit,+sse,+sse2,+sse3,+ssse3,+sse4.1,+sse4.2,+avx,+f16c,+fma,+avx2,+avx512f,+avx512cd,+avx512bw,+avx512dq,+avx512vl,+avx512vbmi
target=(-mtriple="$(llvm-config --host-target)" -mcpu=znver5 -mattr="$features" -code-model=large -relocation-model=static)
opt -passes=verify -disable-output optimized.bc
llc "${target[@]}" -O2 optimized.bc -o installed.s
failures=0
for variant in upstream patched; do
  c++ "${cxxflags[@]}" -O2 -fPIC -c "$variant/llvm/lib/CodeGen/SplitKit.cpp" -o "$variant/SplitKit.cpp.o"
  cp original-CodeGen.a "$archive"
  llvm-ar r "$archive" "$variant/SplitKit.cpp.o"
  llvm-ranlib "$archive"
  c++ llc.o NewPMDriver.o "${ldflags[@]}" -o "$variant/llc"
  for level in 1 2; do
    status=0
    "$variant/llc" "${target[@]}" -O"$level" -verify-machineinstrs optimized.bc \
      -o "$variant/O$level-verified.s" > "$variant/O$level-verify.log" 2>&1 || status=$?
    printf '%s %s %s\n' "$variant" "$level" "$status" >> verifier-status.txt
    if [ "$variant" = upstream ]; then
      if [ "$status" -eq 0 ] || ! grep -q 'Expected a VR256 register, but got a VR256X register' "$variant/O$level-verify.log"; then
        failures=$((failures + 1))
      fi
    else
      if [ "$status" -ne 0 ]; then failures=$((failures + 1)); fi
    fi
    "$variant/llc" "${target[@]}" -O"$level" optimized.bc -o "$variant/O$level.s"
  done
done
cmp installed.s upstream/O2.s
sha256sum ./*.bc ./*.s ./*.patch upstream/*.o upstream/*.s patched/*.o patched/*.s > hashes.txt
# The patched archive is left in this disposable container for an optional Mesa relink.
# Do not retain large executable copies; all source inputs and compiler commands remain.
test "$failures" -eq 0
