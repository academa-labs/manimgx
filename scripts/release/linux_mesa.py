"""Temporary Mesa compiler attribution; changes only the diagnostic driver's sources."""

import argparse
import hashlib
import json
from pathlib import Path


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected one pinned source match in {path}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def patch(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    directory = source / "src/gallium/auxiliary/gallivm"
    init = directory / "lp_bld_init.c"
    passes = directory / "lp_bld_passmgr.c"
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (init, passes)
    }
    replace(
        init,
        "if (gallivm_perf & GALLIVM_PERF_NO_OPT) {",
        "if ((gallivm_perf & GALLIVM_PERF_NO_OPT) ||\n"
        '          debug_get_bool_option("MANIMGX_DIAGNOSTIC_CODEGEN_O0", false)) {',
    )
    replace(
        passes,
        "if (!(gallivm_perf & GALLIVM_PERF_NO_OPT))",
        "if (!((gallivm_perf & GALLIVM_PERF_NO_OPT) ||\n"
        '         debug_get_bool_option("MANIMGX_DIAGNOSTIC_IR_O0", false)))',
    )
    replace(
        passes,
        '#include "lp_bld_passmgr.h"',
        '#include "lp_bld_passmgr.h"\n'
        "#include <llvm-c/BitWriter.h>\n#include <stdio.h>\n#include <stdlib.h>\n"
        "\nstatic void diagnostic_dump(LLVMModuleRef module, const char *name, const char *stage)\n"
        "{\n"
        '   const char *directory = getenv("MANIMGX_DIAGNOSTIC_DUMP_DIR");\n'
        "   if (!directory) return;\n"
        "   char path[1024];\n"
        '   int size = snprintf(path, sizeof(path), "%s/%s-%s.bc", directory, name, stage);\n'
        "   if (size < 0 || size >= (int)sizeof(path) || LLVMWriteBitcodeToFile(module, path)) abort();\n"
        "}\n",
    )
    replace(
        passes,
        "   LLVMPassBuilderOptionsRef opts = LLVMCreatePassBuilderOptions();",
        '   diagnostic_dump(module, module_name, "before");\n'
        "   LLVMPassBuilderOptionsRef opts = LLVMCreatePassBuilderOptions();",
    )
    replace(
        passes,
        "   LLVMDisposePassBuilderOptions(opts);",
        '   diagnostic_dump(module, module_name, "after");\n'
        "   LLVMDisposePassBuilderOptions(opts);",
    )
    after = {}
    for path in (init, passes):
        data = path.read_bytes()
        (output / path.name).write_bytes(data)
        after[path.name] = hashlib.sha256(data).hexdigest()
    (output / "patch.json").write_text(
        json.dumps({"before_sha256": before, "after_sha256": after}, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare(project: Path, script: Path, output: Path) -> None:
    original = project / "scripts/release/build_lavapipe.sh"
    copy = original.with_name("build_lavapipe.diagnostic.sh")
    copy.write_bytes(original.read_bytes())
    replace(
        copy,
        'tar -xJf "$mesa_sha256"',
        'tar -xJf "$mesa_sha256"\n'
        f'"$python" "{script.resolve()}" patch "mesa-$mesa" "{output.resolve()}"',
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "patch"))
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.source, Path(__file__), args.output)
    else:
        patch(args.source, args.output)


if __name__ == "__main__":
    main()
