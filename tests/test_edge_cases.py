#!/usr/bin/env python3
"""边缘行为验收：预检覆盖度、路径下标、编码、原序、布尔模式、递归深度。"""

from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from json_contract.contract import validate_batch
from json_contract.errors import ContractError
from json_contract.jsonparse import loads_strict

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILURES.append(msg)


# 1) 全部支持关键词同时出现的模式可通过预检，且与成熟库结论一致
full_schema = {
    "$defs": {
        "A": {"type": "integer"},
        "B": {"allOf": [{"$ref": "#/$defs/A"}, {"const": 3}]},
    },
    "$ref": "#/$defs/A",
    "type": ["integer", "null"],
    "const": 3,
    "required": ["x"],
    "allOf": [{"const": 3}],
    "anyOf": [{"const": 3}, {"type": "null"}],
    "oneOf": [{"const": 3}],
    "not": {"const": 4},
    "if": {"const": 3},
    "then": {"required": ["x"]},
    "else": False,
    "dependentSchemas": {"x": True},
    "prefixItems": [{"const": 3}],
    "items": True,
    "contains": {"const": 3},
    "unevaluatedItems": True,
    "properties": {"x": True},
    "additionalProperties": True,
    "unevaluatedProperties": True,
}
try:
    validate_batch(json.dumps({"schema": full_schema, "records": [{"x": 3}]}))
    check(True, "")
except ContractError as exc:
    FAILURES.append(f"full-keyword schema rejected: {exc.path} {exc.message}")

try:
    from jsonschema import Draft202012Validator
    v = Draft202012Validator(full_schema)
    for rec in ({"x": 3}, {"x": 4}, 3, None):
        check(
            validate_batch(json.dumps({"schema": full_schema, "records": [rec]}))
            == [v.is_valid(rec)],
            f"full-keyword divergence at {rec!r}",
        )
except ImportError:
    pass

# 2) 未使用的定义与永远不选的分支也会被预检
def expect_reject(doc: dict, path_part: str | None = None):
    try:
        validate_batch(json.dumps(doc))
        FAILURES.append(f"expected rejection: {doc}")
    except ContractError as exc:
        if path_part and path_part not in exc.path:
            FAILURES.append(
                f"path {exc.path!r} does not contain {path_part!r}: {exc.message}"
            )

expect_reject(
    {"schema": {"$defs": {"Unused": {"enum": [1]}}}, "records": []},
    "Unused",
)
expect_reject(
    {"schema": {"if": True, "then": True, "else": {"minimum": 1}},
     "records": []},
    "else",
)
expect_reject(
    {"schema": {"anyOf": [True, {"badKeyword": 1}]}, "records": []},
    "anyOf[1]",
)
expect_reject(
    {"schema": {"$defs": {"A": True, "B": {"$ref": "#/$defs/Missing"}}},
     "records": []},
    "$ref",
)

# 3) 零基下标路径
expect_reject(
    {"schema": {"allOf": [True, True, {"enum": []}]}, "records": []},
    "allOf[2]",
)
expect_reject(
    {"schema": {"prefixItems": [True, {"type": "nope"}]}, "records": []},
    "prefixItems[1]",
)

# 4) 严格解析器行为
check(loads_strict('{"a": 1, "b": [true, false, null]}') ==
      {"a": 1, "b": [True, False, None]}, "basic parse")
check(loads_strict('[-0]') == [0], "negative zero parses as 0")
check(loads_strict(r'"😀"') == "😀", "surrogate pair merge")
check(loads_strict('"\\u4e2d"') == "中", "unicode escape")
for bad in ['{"a":1,"a":2}', "1.0", "1e2", "[1,]", '{"a":1,}', "00", "-01",
            "01", "[1 2]", "{,}", "tru", "falsx", "nul", '"\\u12"',
            r'"\uDC00"', "['x']", '{"a":}', '[1,,2]', "1.", "-.5"]:
    try:
        loads_strict(bad)
        FAILURES.append(f"parser accepted bad input: {bad!r}")
    except ContractError as exc:
        check(exc.path == "$" and exc.syntax, f"syntax path for {bad!r}")

# 5) 严格模式拒绝 Python json 能接受的重复键 / NaN
for raw, label in [
    (b'{"schema":{},"records":[{"a":1,"a":2}]}', "dup key bytes"),
    (b'{"schema":{},"records":[NaN]}', "NaN"),
    (b'{"schema":{},"records":[Infinity]}', "Infinity"),
    (b'{"schema":{},"records":[-Infinity]}', "-Infinity"),
]:
    try:
        validate_batch(raw)
        FAILURES.append(f"accepted invalid JSON ({label})")
    except ContractError as exc:
        check(exc.syntax and exc.path == "$", f"{label} syntax path")

# 6) 代理对与中文端到端
out = validate_batch(
    '{"schema":{"const":"😀中"},"records":["😀中","x","\\uD83D\\uDE00\\u4E2D"]}'
)
check(out == [True, False, True], f"unicode end-to-end: {out}")

# 7) 大批原序
n = 2000
records = [i if i % 2 == 0 else str(i) for i in range(n)]
out = validate_batch(
    json.dumps({"schema": {"type": "integer"}, "records": records})
)
check(out == [i % 2 == 0 for i in range(n)], "large batch ordering")
check(len(out) == n, "large batch length")

# 8) 布尔模式在组合器/属性中的行为
s = {
    "allOf": [True, True],
    "anyOf": [False, False],
    "properties": {"ok": True, "no": False},
    "additionalProperties": True,
}
check(validate_batch(json.dumps({"schema": s, "records": [{"ok": 1}]}))
      == [False], "boolean schema in combinators")
check(validate_batch(json.dumps({"schema": False, "records": [1, {}, []]}))
      == [False, False, False], "root false")
check(validate_batch(json.dumps({"schema": True, "records": [1, {}, []]}))
      == [True, True, True], "root true")

# 9) CLI 用法错误退出码 1，且不产生输出
proc = subprocess.run(
    [sys.executable, "-I", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cli.py")],
    capture_output=True,
)
check(proc.returncode == 1, f"usage exit code: {proc.returncode}")

# 10) 深度嵌套（无环引用链）可正常求值
import string
names = list(string.ascii_uppercase)[:20]
s = {"$defs": {names[i]: ({"$ref": f"#/$defs/{names[i-1]}"} if i > 0
                          else {"type": "integer"})
               for i in range(20)},
     "$ref": f"#/$defs/{names[19]}"}
check(validate_batch(json.dumps({"schema": s, "records": [1, "x"]}))
      == [True, False], "long ref chain")

def main() -> int:
    if FAILURES:
        print("EDGE-CASE FAILURES:")
        for f in FAILURES:
            print(" -", f)
        return 1
    print("edge-case suite OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
