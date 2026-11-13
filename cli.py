#!/usr/bin/env python3
"""组合契约采集入湖校验后端 —— 命令行入口。

用法:
    python3 -I cli.py <input.json> <output.json>

- 输入：UTF-8 JSON，仅含 schema 与 records
- 成功：原子替换输出文件，内容为布尔数组（空批为 []）
- 失败（词法/语法/预检拒绝）：退出码 2，旧输出文件原样保留，错误写 stderr
- 用法/IO 错误：退出码 1
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from json_contract.contract import process_text  # noqa: E402
from json_contract.errors import ContractError  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: python3 -I cli.py <input.json> <output.json>\n"
        )
        return 1

    input_path, output_path = argv[1], argv[2]

    try:
        with open(input_path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        sys.stderr.write(f"cannot read input: {exc}\n")
        return 1

    try:
        rendered = process_text(raw)
    except ContractError as exc:
        # 整次拒绝：不触碰输出文件，保留旧文件
        sys.stderr.write(json.dumps(exc.to_dict(), ensure_ascii=False) + "\n")
        return 2

    output_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    try:
        # 同目录临时文件 + os.replace 保证原子替换
        fd, tmp_path = tempfile.mkstemp(
            prefix=".contract-", suffix=".tmp", dir=output_dir
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(rendered.encode("utf-8"))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, output_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        sys.stderr.write(f"cannot write output: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
