#!/usr/bin/env python3
"""独立验收：额外拒绝语料 + 关键边界行为。

不依赖成熟校验库，全部通过 CLI 端到端执行（python3 -I），覆盖：
- 重复成员 / 非法 Unicode / 非整数数字词法 / 非法结构（语法错误报 $）
- 非法引用、定义环、$defs 越权与非法名称
- 未支持关键词拒绝、参数形状拒绝
- 顶层形状拒绝
- 失败保留旧输出、成功原子替换
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "cli.py")


def run(raw: str | bytes, prior_output: str | None = None):
    """执行 CLI，返回 (exit_code, stdout, stderr, output_file_content)。"""
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in.json")
        out_path = os.path.join(tmp, "out.json")
        mode = "wb" if isinstance(raw, bytes) else "w"
        with open(in_path, mode) as fh:
            fh.write(raw)
        if prior_output is not None:
            with open(out_path, "w") as fh:
                fh.write(prior_output)
        proc = subprocess.run(
            [sys.executable, "-I", CLI, in_path, out_path],
            capture_output=True,
        )
        content = None
        if os.path.exists(out_path):
            with open(out_path) as fh:
                content = fh.read()
        return proc.returncode, proc.stdout.decode(), proc.stderr.decode(), content


# (名称, 输入, 期望路径, 是否语法错误)
REJECT_CASES = [
    # ---- 语法层（报 $） ----
    ("duplicate member", '{"schema":{},"records":[], "records":[]}', "$", True),
    ("duplicate nested member",
     '{"schema":{"properties":{"a":{"const":1},"a":{"const":2}}},"records":[]}',
     "$", True),
    ("non-integer decimal", '{"schema":{},"records":[1.5]}', "$", True),
    ("non-integer zero decimal", '{"schema":{},"records":[1.0]}', "$", True),
    ("non-integer exponent", '{"schema":{},"records":[1e3]}', "$", True),
    ("non-integer negative exp", '{"schema":{},"records":[-0.1]}', "$", True),
    ("leading zero", '{"schema":{},"records":[01]}', "$", True),
    ("plus sign number", '{"schema":{},"records":[+1]}', "$", True),
    ("bare infinity", '{"schema":{},"records":[Infinity]}', "$", True),
    ("nan literal", '{"schema":{},"records":[NaN]}', "$", True),
    ("lone high surrogate", r'{"schema":{},"records":["\uD800"]}', "$", True),
    ("lone low surrogate", r'{"schema":{},"records":["\uDC00"]}', "$", True),
    ("bad surrogate pair", r'{"schema":{},"records":["\uD800A"]}', "$", True),
    ("invalid unicode hex", r'{"schema":{},"records":["\u12GZ"]}', "$", True),
    ("invalid escape", r'{"schema":{},"records":["\x"]}', "$", True),
    ("unescaped control", '{"schema":{},"records":["a\\tb"]}'.replace("\\t", "\t"),
     "$", True),
    ("trailing comma array", '{"schema":{},"records":[1,]}', "$", True),
    ("trailing comma object", '{"schema":{},"records":[{"a":1,}]}', "$", True),
    ("trailing garbage", '{"schema":{},"records":[]}xxx', "$", True),
    ("unclosed array", '{"schema":{},"records":[1,2', "$", True),
    ("unclosed object", '{"schema":{"type":', "$", True),
    ("empty input", "", "$", True),
    ("single comma", ",", "$", True),
    ("missing colon", '{"schema" {},"records":[]}', "$", True),
    # ---- 语义层（报具体 JSON 路径） ----
    ("unsupported keyword patternProperties",
     '{"schema":{"patternProperties":{}},"records":[]}',
     "$.patternProperties", False),
    ("unsupported keyword propertyNames",
     '{"schema":{"propertyNames":false},"records":[]}',
     "$.propertyNames", False),
    ("unsupported keyword enum",
     '{"schema":{"enum":[1]},"records":[]}', "$.enum", False),
    ("unsupported keyword minimum",
     '{"schema":{"minimum":1},"records":[]}', "$.minimum", False),
    ("unsupported keyword $schema",
     '{"schema":{"$schema":"x"},"records":[]}', "$.$schema", False),
    ("unsupported keyword title",
     '{"schema":{"title":"x"},"records":[]}', "$.title", False),
    ("unsupported keyword uniqueItems",
     '{"schema":{"uniqueItems":true},"records":[]}', "$.uniqueItems", False),
    ("bad type name",
     '{"schema":{"type":"str"},"records":[]}', "$.type", False),
    ("empty type array",
     '{"schema":{"type":[]},"records":[]}', "$.type", False),
    ("duplicate type entries",
     '{"schema":{"type":["string","string"]},"records":[]}', "$.type", False),
    ("required non-array",
     '{"schema":{"required":"a"},"records":[]}', "$.required", False),
    ("required empty",
     '{"schema":{"required":[]},"records":[]}', "$.required", False),
    ("required duplicates",
     '{"schema":{"required":["a","a"]},"records":[]}', "$.required", False),
    ("allOf empty",
     '{"schema":{"allOf":[]},"records":[]}', "$.allOf", False),
    ("anyOf non-schema entry",
     '{"schema":{"anyOf":[1]},"records":[]}', "$.anyOf[0]", False),
    ("not not a schema",
     '{"schema":{"not":1},"records":[]}', "$.not", False),
    ("properties non-object",
     '{"schema":{"properties":[]},"records":[]}', "$.properties", False),
    ("bad ref shape",
     '{"schema":{"$ref":"#/defs/x"},"records":[]}', "$.$ref", False),
    ("missing ref target",
     '{"schema":{"$ref":"#/$defs/x"},"records":[]}', "$.$ref", False),
    ("ref cycle direct",
     '{"schema":{"$ref":"#/$defs/A","$defs":{"A":{"$ref":"#/$defs/A"}}},'
     '"records":[]}',
     None, False),
    ("ref cycle indirect",
     '{"schema":{"$defs":{"A":{"$ref":"#/$defs/B"},'
     '"B":{"$ref":"#/$defs/A"}}},"records":[]}',
     None, False),
    ("defs non-root",
     '{"schema":{"properties":{"a":{"$defs":{"X":true}}}},"records":[]}',
     "$.properties.a.$defs", False),
    ("defs bad name digit",
     '{"schema":{"$defs":{"X1":true}},"records":[]}',
     "$.$defs.X1", False),
    ("defs bad name underscore",
     '{"schema":{"$defs":{"_a":true}},"records":[]}',
     "$.$defs._a", False),
    ("defs not object",
     '{"schema":{"$defs":[]},"records":[]}', "$.$defs", False),
    ("top-level extra key",
     '{"schema":{},"records":[],"extra":1}', "$", False),
    ("top-level missing key",
     '{"schema":{}}', "$", False),
    ("top-level not object",
     '[]', "$", False),
    ("records not array",
     '{"schema":{},"records":{}}', "$.records", False),
    ("schema not object",
     '{"schema":1,"records":[]}', "$", False),
    ("prefixItems empty",
     '{"schema":{"prefixItems":[]},"records":[]}', "$.prefixItems", False),
    ("dependentSchemas bad value",
     '{"schema":{"dependentSchemas":{"a":1}},"records":[]}',
     "$.dependentSchemas.a", False),
]


def main() -> int:
    failures = []
    for name, raw, want_path, is_syntax in REJECT_CASES:
        code, _out, err, content = run(raw, prior_output='["OLD"]')
        if code != 2:
            failures.append(f"{name}: expected exit 2, got {code}; stderr={err}")
            continue
        try:
            payload = json.loads(err.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            failures.append(f"{name}: stderr is not JSON: {err!r}")
            continue
        if payload["syntax"] != is_syntax:
            failures.append(
                f"{name}: syntax flag {payload['syntax']} != {is_syntax}"
            )
        if want_path is not None and payload["path"] != want_path:
            failures.append(
                f"{name}: path {payload['path']!r} != {want_path!r}"
            )
        if content != '["OLD"]':
            failures.append(
                f"{name}: rejected run must keep old output, got {content!r}"
            )

    # 非法 UTF-8 字节
    code, _o, err, content = run(
        b'{"schema":{},"records":["\xff\xfe"]}', prior_output='["OLD"]'
    )
    if code != 2 or json.loads(err.strip())["path"] != "$":
        failures.append(f"invalid utf8: code={code} err={err!r}")
    if content != '["OLD"]':
        failures.append(f"invalid utf8: old output changed: {content!r}")

    # BOM 拒绝
    code, _o, err, _c = run(b'\xef\xbb\xbf{"schema":{},"records":[]}')
    if code != 2:
        failures.append(f"BOM: expected reject, got {code} {err!r}")

    # 成功路径：原子替换旧文件；-0 合法；空批输出 []
    ok_cases = [
        ('{"schema":{},"records":[]}', "[]\n"),
        ('{"schema":{},"records":[-0]}', "[true]\n"),
        ('{"schema":{"type":"integer"},"records":[0,-5,99999999999]}',
         "[true,true,true]\n"),
    ]
    for raw, want in ok_cases:
        code, _o, err, content = run(raw, prior_output='["OLD"]')
        if code != 0:
            failures.append(f"ok case {raw!r}: exit {code} err={err!r}")
        elif content != want:
            failures.append(f"ok case {raw!r}: {content!r} != {want!r}")

    if failures:
        print("REJECTION SUITE FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print(f"rejection suite OK ({len(REJECT_CASES) + 3} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
