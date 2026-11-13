#!/usr/bin/env python3
"""合法交集差分验收：本实现 vs 成熟 2020-12 库 jsonschema。

约束（合法交集）：
- 实例数字只生成整数字面量（本实现按契约拒绝浮点词法）
- 模式只使用本实现支持的关键词与受约束的 $ref/$defs
- $defs 仅在根，名称 [A-Za-z]+，定义图为 DAG（反向引用保证无环）

对每个随机 (schema, instance) 对比较双方布尔结论；
另在契约层验证原序输出与空批。
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jsonschema import Draft202012Validator  # noqa: E402

from json_contract.contract import validate_batch  # noqa: E402
from json_contract.evaluator import evaluate  # noqa: E402
from json_contract.precheck import precheck  # noqa: E402

KEYS = ["a", "b", "c", "d", "x", "1key", "带中文"]
STRINGS = ["", "a", "abc", "带中文", "1", "true"]
TYPE_NAMES = ["null", "boolean", "object", "array", "number", "string", "integer"]


def gen_instance(rng: random.Random, depth: int):
    if depth <= 0:
        choices = [
            lambda: None,
            lambda: rng.choice([True, False]),
            lambda: rng.randint(-9, 9),
            lambda: rng.choice(STRINGS),
        ]
        return rng.choice(choices)()
    kind = rng.randrange(7)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return rng.randint(-99, 99)
    if kind == 3:
        return rng.choice(STRINGS)
    if kind == 4:
        return [gen_instance(rng, depth - 1) for _ in range(rng.randrange(4))]
    if kind == 5:
        n = rng.randrange(4)
        return {rng.choice(KEYS): gen_instance(rng, depth - 1) for _ in range(n)}
    return gen_instance(rng, depth - 1)


def gen_schema(rng: random.Random, depth: int, def_names: list[str],
               allow_defs: bool = False):
    # 布尔模式
    if depth <= 0 or rng.random() < 0.12:
        return rng.choice([True, False])

    node: dict = {}

    if allow_defs and rng.random() < 0.7:
        n_defs = rng.randrange(1, 4)
        names = rng.sample(["A", "B", "C", "D", "E", "F"], n_defs)
        defs = {}
        # 定义 i 只能引用序号更大的定义 => 天然 DAG
        for i, name in enumerate(names):
            later = names[i + 1:]
            defs[name] = gen_schema(
                rng, max(depth - 2, 1), later
            )
        node["$defs"] = defs
        def_names = names

    def sub(d: int = 1):
        return gen_schema(rng, depth - d, def_names)

    if depth <= 1 and (def_names and rng.random() < 0.5):
        node["$ref"] = "#/$defs/" + rng.choice(def_names)
    elif depth <= 1:
        return rng.choice([True, False, {}])
    else:
        if def_names and rng.random() < 0.35:
            node["$ref"] = "#/$defs/" + rng.choice(def_names)

    if rng.random() < 0.55:
        if rng.random() < 0.8:
            node["type"] = rng.choice(TYPE_NAMES)
        else:
            k = rng.randrange(1, 4)
            node["type"] = rng.sample(TYPE_NAMES, k)

    if rng.random() < 0.35:
        node["const"] = gen_instance(rng, max(depth - 1, 1))

    if rng.random() < 0.35:
        k = rng.randrange(1, min(3, len(KEYS)) + 1)
        node["required"] = rng.sample(KEYS, k)

    if rng.random() < 0.4:
        node["allOf"] = [sub() for _ in range(rng.randrange(1, 3))]
    if rng.random() < 0.4:
        node["anyOf"] = [sub() for _ in range(rng.randrange(1, 3))]
    if rng.random() < 0.35:
        node["oneOf"] = [sub() for _ in range(rng.randrange(1, 3))]
    if rng.random() < 0.3:
        node["not"] = sub()
    if rng.random() < 0.3:
        node["if"] = sub()
        if rng.random() < 0.8:
            node["then"] = sub()
        if rng.random() < 0.6:
            node["else"] = sub()
    if rng.random() < 0.3:
        k = rng.randrange(1, 3)
        node["dependentSchemas"] = {
            rng.choice(KEYS): sub() for _ in range(k)
        }
    if rng.random() < 0.4:
        node["prefixItems"] = [sub() for _ in range(rng.randrange(1, 4))]
    if rng.random() < 0.35:
        node["items"] = sub()
    if rng.random() < 0.3:
        node["contains"] = sub()
    if rng.random() < 0.25:
        node["unevaluatedItems"] = sub()
    if rng.random() < 0.4:
        k = rng.randrange(1, 4)
        node["properties"] = {
            rng.choice(KEYS): sub() for _ in range(k)
        }
    if rng.random() < 0.3:
        node["additionalProperties"] = sub()
    if rng.random() < 0.25:
        node["unevaluatedProperties"] = sub()

    if not node:  # 空对象模式 {}
        return {}
    return node


def main() -> int:
    rng = random.Random(20261113)
    pairs = 0
    mismatches: list[str] = []
    batch_checks = 0

    for round_i in range(220):
        schema = gen_schema(rng, depth=4, def_names=[], allow_defs=True)
        # 所有生成的模式都必须通过预检
        precheck({"schema": schema, "records": []})
        validator = Draft202012Validator(schema)
        defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}

        records = [gen_instance(rng, depth=3) for _ in range(rng.randrange(6))]
        ours_batch = validate_batch(
            _encode({"schema": schema, "records": records})
        )
        batch_checks += 1

        for inst in records:
            pairs += 1
            ours = evaluate(schema, inst, defs)
            theirs = validator.is_valid(inst)
            if ours != theirs:
                mismatches.append(
                    f"schema={schema!r}\n  instance={inst!r}\n"
                    f"  ours={ours} jsonschema={theirs}"
                )
                if len(mismatches) >= 10:
                    break

            # 单条契约路径与直接求值一致 + 原序
        expected_batch = [validator.is_valid(r) for r in records]
        if ours_batch != expected_batch:
            mismatches.append(
                f"batch mismatch\nschema={schema!r}\n"
                f"records={records!r}\nours={ours_batch}\nref={expected_batch}"
            )
        if len(mismatches) >= 10:
            break

    # 空批
    assert validate_batch(_encode({"schema": {}, "records": []})) == []
    # 原序：构造可区分顺序的记录
    doc = {
        "schema": {"type": "integer"},
        "records": [1, "x", 2, None, 3],
    }
    assert validate_batch(_encode(doc)) == [True, False, True, False, True]

    if mismatches:
        print("DIFFERENTIAL MISMATCHES:")
        for m in mismatches:
            print("-", m)
        return 1
    print(
        f"differential OK: {pairs} (schema, instance) pairs across "
        f"{batch_checks} schemas; empty-batch and ordering checks passed"
    )
    return 0


def _encode(doc: dict) -> str:
    import json

    # 仅用于测试序列化；解析仍走本实现的严格解析器
    return json.dumps(doc, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(main())
