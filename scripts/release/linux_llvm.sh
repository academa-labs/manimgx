#!/bin/bash
# Temporary, nonexecuting reduction of the retained Mesa shader in its exact LLVM SDK.
set -euo pipefail
input=$(realpath "$1")
mkdir -p "$2"
output=$(realpath "$2")
cd "$output"
cp "$input/default-dump/bitcode/cs5_variant0-after.bc" optimized.bc
cp "$input/ir-o0/bitcode/cs5_variant0-after.bc" minimal.bc
cp "$input/default-dump/bitcode/cs5_variant0-before.bc" before.bc
cp "$input/cpu.txt" "$input/source-run.json" "$input/artifact-hashes.txt" .
printf '%s\n' '211aed8343ed48be225fde8f01b577f23dd593217eb75ed0c914fa2305034ec7  optimized.bc' | sha256sum --check

set -x
dnf -q -y install llvm llvm-devel
test "$(llvm-config --version)" = 21.1.8
llvm-config --version > llvm-version.txt
llc --version > llc-version.txt
rpm -qa | sort > rpm-packages.txt
triple=$(llvm-config --host-target)
# Derived from the retained CPU flags, Mesa 26.2.3 lp_build_fill_mattrs and LLVM 21's
# family 1Ah mapping. MCJIT defaults to large code model and static relocation.
grep -Eq '^CPU family:[[:space:]]+26$' cpu.txt
grep -Eq '^Model:[[:space:]]+2$' cpu.txt
features=+64bit,+sse,+sse2,+sse3,+ssse3,+sse4.1,+sse4.2,+avx,+f16c,+fma,+avx2,+avx512f,+avx512cd,+avx512bw,+avx512dq,+avx512vl,+avx512vbmi
target=(-mtriple="$triple" -mcpu=znver5 -mattr="$features" -code-model=large -relocation-model=static)
for stage in before minimal optimized; do
  llvm-dis "$stage.bc" -o "$stage.ll"
  opt -passes=verify -disable-output "$stage.bc" > "$stage-verify.log" 2>&1
done
verification_failures=0
for level in 0 1 2; do
  status=0
  llc "${target[@]}" -O"$level" -verify-machineinstrs optimized.bc \
    -o "optimized-O$level-verified.s" > "optimized-O$level-verify.log" 2>&1 || status=$?
  printf '%s %s\n' "$level" "$status" >> machine-verifier-status.txt
  if [ "$status" -ne 0 ]; then
    verification_failures=$((verification_failures + 1))
  fi
  # Preserve ordinary emitted code too: Mesa does not enable the machine verifier.
  llc "${target[@]}" -O"$level" optimized.bc -o "optimized-O$level.s"
done
status=0
llc "${target[@]}" -O2 -verify-machineinstrs minimal.bc \
  -o minimal-O2-verified.s > minimal-O2-verify.log 2>&1 || status=$?
printf 'minimal-2 %s\n' "$status" >> machine-verifier-status.txt
if [ "$status" -ne 0 ]; then
  verification_failures=$((verification_failures + 1))
fi
llc "${target[@]}" -O2 minimal.bc -o minimal-O2.s
llc "${target[@]}" -O2 -stop-after=finalize-isel optimized.bc -o optimized-isel.mir
llc "${target[@]}" -O2 -stop-before=greedy optimized.bc -o optimized-before-regalloc.mir
llc "${target[@]}" -O2 -stop-after=greedy optimized.bc -o optimized-greedy.mir
llc "${target[@]}" -O2 -stop-after=virtregrewriter optimized.bc -o optimized-after-regalloc.mir
llc "${target[@]}" -O2 -print-after-all -filter-print-funcs=cs_variant optimized.bc \
  -o optimized-traced.s 2> optimized-passes.log
cmp optimized-O2.s optimized-traced.s
sha256sum ./*.bc ./*.ll ./*.s ./*.mir > hashes.txt
test "$verification_failures" -eq 0
