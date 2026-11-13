"""对外主入口：解析 -> 预检 -> 逐条求值，原序返回布尔数组。"""

from __future__ import annotations

import sys

from .errors import ContractError
from .evaluator import evaluate
from .jsonparse import loads_strict
from .precheck import precheck

# 解析/预检/求值均为递归实现；抬高栈限制以容纳深嵌套，
# 再兜底把 RecursionError 转成整洁的契约拒绝。
_RECURSION_LIMIT = 5000


def validate_batch(raw: bytes | str) -> list[bool]:
    """处理一批采集入湖请求。

    :param raw: UTF-8 JSON 文本，仅含 ``schema`` 与 ``records`` 数组
    :returns: 与 records 同序的布尔数组；空批为 ``[]``
    :raises ContractError: 词法/语法错误、模式预检失败等整次拒绝场景
    """
    previous_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(_RECURSION_LIMIT)
    try:
        document = loads_strict(raw)
        precheck(document)
        schema = document["schema"]
        defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
        records = document["records"]
        # 逐条独立求值；模式已预检通过（DAG），求值不再抛契约错误
        try:
            output = [evaluate(schema, record, defs) for record in records]
        except RecursionError as exc:
            raise ContractError(
                "nested structure too deep", path="$", syntax=False
            ) from exc
        return output
    except RecursionError as exc:
        raise ContractError(
            "nested structure too deep", path="$", syntax=False
        ) from exc
    finally:
        sys.setrecursionlimit(previous_limit)


def process_text(raw: bytes | str) -> str:
    """返回应写入输出文件的 JSON 文本（UTF-8、末尾换行）。"""
    result = validate_batch(raw)
    return _dumps(result) + "\n"


def _dumps(value: list[bool]) -> str:
    # 布尔数组极小，自行序列化以保持输出确定且无第三方依赖
    return "[" + ",".join("true" if v else "false" for v in value) + "]"
