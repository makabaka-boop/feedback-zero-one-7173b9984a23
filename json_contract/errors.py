"""统一错误类型。

任何使整次请求被拒绝的问题都抛出 :class:`ContractError`。
``path`` 为 JSON 路径（根节点用 ``$``，数组段为 ``[i]``，零基下标）。
``syntax`` 为 True 时表示词法/语法层错误，按规范路径固定为 ``$``。
"""

from __future__ import annotations


class ContractError(Exception):
    def __init__(self, message: str, path: str = "$", syntax: bool = False):
        super().__init__(message)
        self.message = message
        # 语法错误一律报 $
        self.path = "$" if syntax else (path or "$")
        self.syntax = syntax

    def to_dict(self) -> dict:
        return {
            "error": self.message,
            "path": self.path,
            "index": _last_array_index(self.path),
            "syntax": self.syntax,
        }


def _last_array_index(path: str) -> int | None:
    """从路径中取最后一个数组段的零基下标，无数组段时为 None。"""
    if "[" not in path:
        return None
    last = path.rstrip("]").rsplit("[", 1)[-1]
    try:
        return int(last)
    except ValueError:
        return None
