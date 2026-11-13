#!/usr/bin/env python3
"""语义单元验收：有效信息冒泡、组合器分支选择、边界类型语义。

每条用例同时对照成熟 jsonschema（若可用）与本实现。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from json_contract.contract import validate_batch  # noqa: E402
from json_contract.evaluator import evaluate  # noqa: E402

try:
    from jsonschema import Draft202012Validator
    HAVE_REF = True
except ImportError:  # 无对照库时仍可独立运行
    HAVE_REF = False

# (名称, schema, [(instance, expected_bool), ...])
CASES = [
    ("spec-example",
     {"contains": {"const": 1}, "unevaluatedItems": False},
     [([1, 1], True), ([1, 2], False), ([], False)]),

    ("anyof-merges-success-branches",
     {"anyOf": [
         {"properties": {"a": {"const": 1}}},
         {"properties": {"b": {"const": 2}}}],
      "unevaluatedProperties": False},
     [({"a": 1}, True), ({"b": 2}, True), ({"c": 3}, False),
      ({"a": 1, "b": 2}, True)]),

    ("oneof-sole-match-bubbles",
     {"oneOf": [
         {"properties": {"a": True}, "unevaluatedProperties": False},
         {"properties": {"b": True}, "unevaluatedProperties": False}]},
     [({"a": 1}, True), ({"b": 2}, True), ({"a": 1, "b": 2}, False),
      ({"c": 1}, False), ({}, False)]),

    ("anyof-annotation-bubbles-to-neighbor",
     {"anyOf": [
         {"properties": {"a": True}},
         {"properties": {"b": True}}],
      "unevaluatedProperties": False},
     [({"a": 1}, True), ({"b": 2}, True), ({"a": 1, "b": 2}, True),
      ({"c": 1}, False), ({}, True)]),

    ("not-no-annotations",
     {"not": {"required": ["a"]},
      "unevaluatedProperties": False},
     [({"a": 1}, False), ({"b": 1}, False), ({}, True)]),

    ("if-then-else-selection",
     {"if": {"type": "object"},
      "then": {"required": ["a"]},
      "else": {"type": "string"}},
     [({"a": 1}, True), ({}, False), ("x", True), (1, False)]),

    ("then-annotation-only-when-selected",
     {"if": {"const": 1},
      "then": {"properties": {"a": True}},
      "unevaluatedProperties": False},
     [(1, True), ({"a": 1, "b": 2}, False),
      # if 失败 -> then 不执行 -> 没有任何属性被标记
      ({"b": 2}, False), ({}, True)]),

    ("ref-bubbles-annotations",
     {"$defs": {"P": {"properties": {"a": True}}},
      "$ref": "#/$defs/P",
      "unevaluatedProperties": False},
     [({"a": 1}, True), ({"z": 1}, False)]),

    ("ref-and-siblings-and",
     {"$defs": {"P": {"type": "object"}},
      "$ref": "#/$defs/P",
      "required": ["a"]},
     [({"a": 1}, True), ({}, False), ([], False)]),

    ("additional-properties-only-same-level",
     {"properties": {"a": True},
      "additionalProperties": False},
     [({"a": 1}, True), ({"a": 1, "b": 2}, False)]),

    ("additional-inside-anyof-not-visible-outside",
     {"anyOf": [{"properties": {"a": True},
                 "additionalProperties": False}],
      "unevaluatedProperties": False},
     [({"a": 1}, True), ({"a": 1, "b": 2}, False)]),

    ("prefix-items-and-unevaluated",
     {"prefixItems": [{"const": 0}, {"const": 1}],
      "unevaluatedItems": False},
     [([0, 1], True), ([0, 1, 2], False), ([0], True), ([1], False)]),

    ("items-covers-rest",
     {"prefixItems": [{"const": 0}],
      "items": {"type": "integer"},
      "unevaluatedItems": False},
     [([0, 1, 2], True), ([0, "x"], False), ([0], True)]),

    ("contains-marks-matched-indices",
     {"contains": {"const": 1},
      "unevaluatedItems": {"type": "integer"}},
     [([1, 2, 3], True), ([1, "x"], False), ([], False), ([2, 1], True)]),

    ("dependent-schemas",
     {"dependentSchemas": {"a": {"required": ["b"]}}},
     [({"a": 1, "b": 2}, True), ({"a": 1}, False), ({"b": 2}, True),
      ({}, True)]),

    ("boolean-schemas",
     {"properties": {"a": True, "b": False},
      "additionalProperties": True},
     [({"a": 1}, True), ({"b": 1}, False), ({"c": 1}, True)]),

    ("type-integer-number-bool",
     {"type": "integer"},
     [(1, True), (True, False), (-5, True)]),

    ("type-number-accepts-integer",
     {"type": "number"},
     [(1, True), ("1", False), (True, False)]),

    ("type-array-multi",
     {"type": ["string", "null"]},
     [("x", True), (None, True), (1, False), (False, False)]),

    ("const-bool-vs-int",
     {"const": 1},
     [(1, True), (True, False), (0, False)]),

    ("const-deep",
     {"const": {"a": [1, {"b": "x"}]}},
     [({"a": [1, {"b": "x"}]}, True),
      ({"a": [1, {"b": "y"}]}, False),
      ({"a": [1, {"b": "x"}], "c": 0}, False)]),

    ("required-missing",
     {"required": ["a", "b"]},
     [({"a": 1, "b": 2}, True), ({"a": 1}, False), ({}, False),
      ([], True), ("x", True)]),

    ("nested-ref-in-anyof",
     {"$defs": {"Str": {"type": "string"}, "Int": {"type": "integer"}},
      "anyOf": [{"$ref": "#/$defs/Str"}, {"$ref": "#/$defs/Int"}]},
     [("a", True), (1, True), ([], False), (True, False)]),

    ("unevaluated-items-through-allof",
     {"allOf": [{"prefixItems": [{"type": "integer"}]}],
      "unevaluatedItems": False},
     [([1], True), ([1, "x"], False), ([], True)]),

    ("empty-schema-accepts-all",
     {},
     [(1, True), ("x", True), (None, True), ([], True), ({}, True),
      (True, True)]),
]


def main() -> int:
    failures = []
    for name, schema, pairs in CASES:
        defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
        records = [inst for inst, _ in pairs]
        # 契约层（经严格解析器）
        import json
        rendered = json.dumps({"schema": schema, "records": records},
                              ensure_ascii=False)
        batch = validate_batch(rendered)
        for (inst, want), got in zip(pairs, batch):
            if got != want:
                failures.append(f"{name}: instance={inst!r} got={got} want={want}")
        # 直接求值 + 成熟库对照
        for inst, want in pairs:
            got = evaluate(schema, inst, defs)
            if got != want:
                failures.append(f"{name} (direct): {inst!r} got={got} want={want}")
            if HAVE_REF:
                ref = Draft202012Validator(schema).is_valid(inst)
                if ref != want:
                    failures.append(
                        f"{name}: TEST BUG vs jsonschema: {inst!r} ref={ref} want={want}"
                    )
                if got != ref:
                    failures.append(
                        f"{name}: DIVERGENCE {inst!r} ours={got} ref={ref}"
                    )

    if failures:
        print("SEMANTIC FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print(f"semantic suite OK ({len(CASES)} cases, reference lib: "
          f"{'yes' if HAVE_REF else 'no'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
