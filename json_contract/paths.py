"""JSON 路径工具。

路径风格：根 ``$``；对象成员 ``$.foo``（简单标识符）或 ``$['a.b']``；
数组成员 ``[i]``（零基下标）。
"""

from __future__ import annotations

_SIMPLE = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$"
)


def child(path: str, key) -> str:
    """追加一个对象成员或数组下标段。

    简单标识符（字母/下划线/$ 开头，后接字母数字下划线/$）用点号段，
    其余键用括号引号段；数组下标用 [i]。
    """
    if isinstance(key, int):
        return f"{path}[{key}]"
    key = str(key)
    if key and all(ch in _SIMPLE for ch in key) and not key[0].isdigit():
        return f"{path}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{path}['{escaped}']"
