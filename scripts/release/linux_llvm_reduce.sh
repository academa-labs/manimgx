#!/bin/bash
# Temporary bounded reduction of the compiler's register-class verifier failure.
set -euo pipefail
ulimit -c 0
input=$(realpath "$1")
mkdir -p "$2"
output=$(realpath "$2")
cd "$output"
cp "$input/default-dump/bitcode/cs5_variant0-after.bc" optimized.bc
printf '%s\n' '211aed8343ed48be225fde8f01b577f23dd593217eb75ed0c914fa2305034ec7  optimized.bc' | sha256sum --check
set -x
dnf -q -y install llvm llvm-devel
test "$(llvm-config --version)" = 21.1.8
llvm-reduce --version > reducer-version.txt
llvm-reduce --print-delta-passes > reducer-passes.txt
rpm -qa | sort > rpm-packages.txt
export features=+64bit,+sse,+sse2,+sse3,+ssse3,+sse4.1,+sse4.2,+avx,+f16c,+fma,+avx2,+avx512f,+avx512cd,+avx512bw,+avx512dq,+avx512vl,+avx512vbmi
export triple
triple=$(llvm-config --host-target)
target=(-mtriple="$triple" -mcpu=znver5 -mattr="$features" -code-model=large -relocation-model=static)
opt -passes=verify -disable-output optimized.bc
llvm-dis optimized.bc -o original.ll
llc "${target[@]}" -O2 -stop-before=greedy optimized.bc -o original.mir
cat > interesting.sh <<'TEST'
#!/bin/bash
set -eu
ulimit -c 0
log=$(mktemp)
trap 'rm -f "$log"' EXIT
target=(-mtriple="$triple" -mcpu=znver5 -mattr="$features" -code-model=large -relocation-model=static)
if [ "$mode" = mir ]; then
  llc "${target[@]}" -run-pass=none -verify-machineinstrs "$1" -o /dev/null > "$log" 2>&1 || exit 1
  target+=(-run-pass=greedy)
else
  opt -passes=verify -disable-output "$1" || exit 1
fi
status=0
llc "${target[@]}" -O2 -verify-machineinstrs "$1" -o /dev/null > "$log" 2>&1 || status=$?
test "$status" -ne 0
grep -q 'AVX2_SETALLONES' "$log"
grep -q 'Expected a VR256 register, but got a VR256X register' "$log"
TEST
chmod +x interesting.sh
export mode=mir
if ! ./interesting.sh original.mir > mir-control.log 2>&1; then
  mode=ll
fi
./interesting.sh "original.$mode"
printf '%s\n' "$mode" > reduction-mode.txt
cp "original.$mode" "reduced.$mode"
status=0
# This is a compile-only verifier witness. It is not executed as a reduced shader.
# Avoid the explicit poison-substitution pass; every retained IR still passes verify.
timeout --kill-after=10s 300s llvm-reduce --test="$(pwd)/interesting.sh" \
  --max-pass-iterations=1 --skip-delta-passes=operands-poison -j=2 \
  -o "reduced.$mode" "original.$mode" > reduction.log 2>&1 || status=$?
printf '%s\n' "$status" > reduction-status.txt
test "$status" -eq 0 || test "$status" -eq 124
./interesting.sh "reduced.$mode"
wc -l "original.$mode" "reduced.$mode" > reduction-size.txt
sha256sum optimized.bc "original.$mode" "reduced.$mode" interesting.sh > hashes.txt
