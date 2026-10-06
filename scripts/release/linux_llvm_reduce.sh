#!/bin/bash
# Temporary bounded reduction of the compiler's register-class verifier failure.
set -euo pipefail
ulimit -c 0
input=$(realpath "$1")
checkpoint=$(realpath "$3")
mkdir -p "$2"
output=$(realpath "$2")
cd "$output"
cp "$input/default-dump/bitcode/cs5_variant0-after.bc" optimized.bc
printf '%s\n' '211aed8343ed48be225fde8f01b577f23dd593217eb75ed0c914fa2305034ec7  optimized.bc' | sha256sum --check
set -x
dnf -q -y install llvm llvm-devel
test "$(llvm-config --version)" = 21.1.8
command -v flock
llvm-reduce --version > reducer-version.txt
llvm-reduce --print-delta-passes > reducer-passes.txt
rpm -qa | sort > rpm-packages.txt
export features=+64bit,+sse,+sse2,+sse3,+ssse3,+sse4.1,+sse4.2,+avx,+f16c,+fma,+avx2,+avx512f,+avx512cd,+avx512bw,+avx512dq,+avx512vl,+avx512vbmi
export triple
triple=$(llvm-config --host-target)
export reduction_output="$output"
opt -passes=verify -disable-output optimized.bc
printf '%s  %s\n' 1a496fc0ed8ed75f3223be4aafa3e76905855a88aae1e14f62673cc87e91a1f9 "$checkpoint/reduced.ll" | sha256sum --check
cp "$checkpoint/reduced.ll" original.ll
cat > interesting.sh <<'TEST'
#!/bin/bash
set -eu
ulimit -c 0
log=$(mktemp)
trap 'rm -f "$log"' EXIT
target=(-mtriple="$triple" -mcpu=znver5 -mattr="$features" -code-model=large -relocation-model=static)
opt -passes=verify -disable-output "$1" || exit 1
status=0
llc "${target[@]}" -O2 -verify-machineinstrs "$1" -o /dev/null > "$log" 2>&1 || status=$?
test "$status" -ne 0
grep -q 'AVX2_SETALLONES' "$log"
grep -q 'Expected a VR256 register, but got a VR256X register' "$log"
# llvm-reduce saves only after a complete delta pass. Preserve verified smaller
# candidates during a pass too, so the bounded run does not discard that work.
(
  flock 9
  best="$reduction_output/best.ll"
  bytes=$(wc -c < "$1")
  if [ ! -f "$best" ] || [ "$bytes" -lt "$(wc -c < "$best")" ]; then
    cp "$1" "$best.new"
    mv "$best.new" "$best"
  fi
) 9> "$reduction_output/best.lock"
TEST
chmod +x interesting.sh
./interesting.sh original.ll
cp original.ll reduced.ll
passes=instructions,basic-blocks,simplify-cfg,arguments,operands-zero,operands-one
status=0
# This is a compile-only verifier witness. It is not executed as a reduced shader.
# Avoid the explicit poison-substitution pass; every retained IR still passes verify.
timeout --kill-after=10s 300s llvm-reduce --test="$(pwd)/interesting.sh" \
  --max-pass-iterations=1 --delta-passes="$passes" -j=2 \
  -o reduced.ll original.ll > reduction.log 2>&1 || status=$?
printf '%s\n' "$status" > reduction-status.txt
test "$status" -eq 0 || test "$status" -eq 124
./interesting.sh reduced.ll
cp best.ll reduced.ll
./interesting.sh reduced.ll
wc -l original.ll reduced.ll > reduction-size.txt
sha256sum optimized.bc original.ll reduced.ll interesting.sh > hashes.txt
