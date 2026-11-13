#!/usr/bin/env python3
"""大规模多种子差分模糊（需成熟库 jsonschema 可导入）。

复用 test_differential 的生成器，跑 5 个固定种子、约 9k 对 (schema, instance)。
"""

from __future__ import annotations

import random
import sys

from jsonschema import Draft202012Validator

from json_contract.evaluator import evaluate
from json_contract.precheck import precheck
from tests.test_differential import gen_instance, gen_schema

SEEDS = (1, 42, 777, 90210, 31337)


def main() -> int:
    total = 0
    for seed in SEEDS:
        rng = random.Random(seed)
        for _ in range(400):
            schema = gen_schema(rng, depth=5, def_names=[], allow_defs=True)
            precheck({"schema": schema, "records": []})
            validator = Draft202012Validator(schema)
            defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
            for _ in range(rng.randrange(1, 9)):
                inst = gen_instance(rng, depth=4)
                total += 1
                ours = evaluate(schema, inst, defs)
                theirs = validator.is_valid(inst)
                if ours != theirs:
                    print(f"MISMATCH seed={seed}")
                    print(" schema =", schema)
                    print(" instance =", inst)
                    print(f" ours={ours} jsonschema={theirs}")
                    return 1
    print(f"large-scale differential OK: {total} pairs across {len(SEEDS)} seeds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
