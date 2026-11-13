#!/usr/bin/env python3
"""一键验收入口。

- 独立套件（不依赖成熟库）：拒绝语料、边缘行为
- 差分套件（需要 jsonschema，通过 PYTHONPATH 提供即可；缺失则跳过并提示）

注意：本验收器需要读取 PYTHONPATH 以定位可选的对照库，因此不要用 -I 运行；
交付程序 cli.py 本身仍按 ``python3 -I cli.py`` 运行。

退出码 0 表示全部通过。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

RESULTS: list[tuple[str, bool, str]] = []


def run_module(name: str, path: str) -> None:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        rc = module.main()
        RESULTS.append((name, rc == 0, "" if rc == 0 else f"exit {rc}"))
    except Exception:  # noqa: BLE001 - 验收脚本要捕获全部异常并汇总
        RESULTS.append((name, False, traceback.format_exc()))


def main() -> int:
    tests_dir = os.path.join(ROOT, "tests")

    # 独立套件（-I 语义：不依赖第三方库）
    run_module("test_rejections", os.path.join(tests_dir, "test_rejections.py"))
    run_module("test_edge_cases", os.path.join(tests_dir, "test_edge_cases.py"))

    have_ref = importlib.util.find_spec("jsonschema") is not None
    if have_ref:
        run_module("test_semantics", os.path.join(tests_dir, "test_semantics.py"))
        run_module("test_differential",
                   os.path.join(tests_dir, "test_differential.py"))
        run_module("test_fuzz_large",
                   os.path.join(tests_dir, "test_fuzz_large.py"))
    else:
        RESULTS.append(
            ("reference-differential", True,
             "SKIPPED: jsonschema not on PYTHONPATH (independent suites still ran)")
        )

    width = max(len(n) for n, _, _ in RESULTS)
    print()
    for name, ok, detail in RESULTS:
        status = "PASS" if ok else "FAIL"
        line = f"[{status}] {name.ljust(width)}"
        if detail:
            line += f"  {detail}"
        print(line)

    return 0 if all(ok for _, ok, _ in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
