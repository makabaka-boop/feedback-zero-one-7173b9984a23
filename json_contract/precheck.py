"""模式预检：在任何求值之前检查全部模式（含未使用的定义与分支）。

覆盖：
- 输入顶层形状（仅含 schema / records，records 为数组）
- 关键词白名单（其余关键词整次拒绝）
- 各关键词参数形状（布尔模式、数组/对象/字符串类型等）
- ``$defs`` 仅根可用，名称匹配 [A-Za-z]+
- ``$ref`` 仅收 ``#/$defs/名称`` 且目标存在
- 定义引用图无环
"""

from __future__ import annotations

import re

from .errors import ContractError
from .paths import child

# 支持的全部关键词（JSON Schema 2020-12 子集）
SUPPORTED_KEYWORDS = frozenset(
    {
        # Core（§10）
        "$ref",
        "$defs",
        # Validation 仅三个
        "type",
        "const",
        "required",
        # Applicator（除 patternProperties、propertyNames 外全部）
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "dependentSchemas",
        "prefixItems",
        "items",
        "contains",
        "unevaluatedItems",
        "properties",
        "additionalProperties",
        "unevaluatedProperties",
    }
)

TYPE_NAMES = frozenset(
    {"null", "boolean", "object", "array", "number", "string", "integer"}
)
_DEF_NAME_RE = re.compile(r"^[A-Za-z]+$")
_REF_RE = re.compile(r"^#/\$defs/([A-Za-z]+)$")
_TOP_KEYS = frozenset({"schema", "records"})


def precheck(document) -> None:
    """对已解析的整份输入文档做预检，不合格抛 :class:`ContractError`。"""
    if not isinstance(document, dict):
        raise ContractError("top-level input must be an object", path="$")
    if set(document.keys()) != _TOP_KEYS:
        raise ContractError(
            "top-level input must contain exactly 'schema' and 'records'",
            path="$",
        )
    records = document["records"]
    if not isinstance(records, list):
        raise ContractError("'records' must be an array", path=child("$", "records"))

    schema = document["schema"]
    # 收集所有 $ref 出现位置：(path, 目标名)
    refs: list[tuple[str, str]] = []
    _check_schema(schema, "$", is_root=True, refs=refs)

    defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
    def_names = set(defs.keys()) if isinstance(defs, dict) else set()

    # 引用目标必须存在
    for ref_path, target in refs:
        if target not in def_names:
            raise ContractError(
                f"$ref target '#/$defs/{target}' does not exist",
                path=ref_path,
            )

    # 定义引用图无环：节点为 def 名称，边为定义内出现的 $ref
    graph: dict[str, set[str]] = {name: set() for name in def_names}
    for ref_path, target in refs:
        # ref_path 形如 $.$defs.Name... 或子模式内路径
        marker = "$.$defs."
        if ref_path.startswith(marker):
            owner = ref_path[len(marker):].split(".", 1)[0].split("[", 1)[0]
            if owner in graph:
                graph[owner].add(target)
    _assert_acyclic(graph, refs)


def _assert_acyclic(graph: dict[str, set[str]], refs: list[tuple[str, str]]) -> None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in graph}

    def visit(node: str, stack: list[str]) -> None:
        color[node] = GRAY
        stack.append(node)
        for nxt in graph[node]:
            if color[nxt] == GRAY:
                cycle = " -> ".join(stack[stack.index(nxt):] + [nxt])
                # 多错任选：报环上第一个 $ref 的路径
                ref_path = next(
                    (p for p, t in refs if t == nxt and p.startswith("$.$defs.")),
                    "$",
                )
                raise ContractError(
                    f"cyclic $defs reference detected: {cycle}", path=ref_path
                )
            if color[nxt] == WHITE:
                visit(nxt, stack)
        stack.pop()
        color[node] = BLACK

    for name in graph:
        if color[name] == WHITE:
            visit(name, [])


def _is_schema(node) -> bool:
    return isinstance(node, bool) or isinstance(node, dict)


def _check_schema(node, path: str, *, is_root: bool, refs: list[tuple[str, str]]) -> None:
    if isinstance(node, bool):
        return  # 布尔模式，无关键词
    if not isinstance(node, dict):
        raise ContractError("schema must be a boolean or an object", path=path)

    for keyword in node:
        if keyword not in SUPPORTED_KEYWORDS:
            raise ContractError(
                f"unsupported keyword {keyword!r}", path=child(path, keyword)
            )

    # $defs 仅根可用，名称 [A-Za-z]+
    if "$defs" in node:
        if not is_root:
            raise ContractError(
                "$defs is only allowed at the root schema",
                path=child(path, "$defs"),
            )
        defs = node["$defs"]
        if not isinstance(defs, dict):
            raise ContractError(
                "$defs must be an object", path=child(path, "$defs")
            )
        for name, sub in defs.items():
            if not _DEF_NAME_RE.fullmatch(name):
                raise ContractError(
                    f"$defs name {name!r} must match [A-Za-z]+",
                    path=child(child(path, "$defs"), name),
                )
            _check_schema(
                sub,
                child(child(path, "$defs"), name),
                is_root=False,
                refs=refs,
            )

    if "$ref" in node:
        ref = node["$ref"]
        if not isinstance(ref, str):
            raise ContractError("$ref must be a string", path=child(path, "$ref"))
        m = _REF_RE.fullmatch(ref)
        if not m:
            raise ContractError(
                "$ref must be of the form '#/$defs/<name>' with name [A-Za-z]+",
                path=child(path, "$ref"),
            )
        refs.append((child(path, "$ref"), m.group(1)))

    # ---- Validation 三关键词 ----
    if "type" in node:
        t = node["type"]
        if isinstance(t, str):
            if t not in TYPE_NAMES:
                raise ContractError(
                    f"unknown type name {t!r}", path=child(path, "type")
                )
        elif isinstance(t, list):
            if not t:
                raise ContractError(
                    "'type' array must not be empty", path=child(path, "type")
                )
            for i, item in enumerate(t):
                if not isinstance(item, str) or item not in TYPE_NAMES:
                    raise ContractError(
                        "'type' array entries must be valid type names",
                        path=child(child(path, "type"), i),
                    )
            if len(set(t)) != len(t):
                raise ContractError(
                    "'type' array must not contain duplicate entries",
                    path=child(path, "type"),
                )
        else:
            raise ContractError(
                "'type' must be a string or an array of strings",
                path=child(path, "type"),
            )

    # const：任意 JSON 值均合法（解析器已保证形状）

    if "required" in node:
        req = node["required"]
        if not isinstance(req, list) or not req:
            raise ContractError(
                "'required' must be a non-empty array of strings",
                path=child(path, "required"),
            )
        for i, item in enumerate(req):
            if not isinstance(item, str):
                raise ContractError(
                    "'required' entries must be strings",
                    path=child(child(path, "required"), i),
                )
        if len(set(req)) != len(req):
            raise ContractError(
                "'required' must not contain duplicate entries",
                path=child(path, "required"),
            )

    # ---- Applicator 数组类 ----
    for kw in ("allOf", "anyOf", "oneOf"):
        if kw in node:
            arr = node[kw]
            if not isinstance(arr, list) or not arr:
                raise ContractError(
                    f"'{kw}' must be a non-empty array of schemas",
                    path=child(path, kw),
                )
            for i, sub in enumerate(arr):
                if not _is_schema(sub):
                    raise ContractError(
                        f"'{kw}' entries must be schemas",
                        path=child(child(path, kw), i),
                    )
                _check_schema(
                    sub, child(child(path, kw), i), is_root=False, refs=refs
                )

    for kw in ("not", "if", "then", "else", "items", "contains",
               "unevaluatedItems", "additionalProperties", "unevaluatedProperties"):
        if kw in node:
            sub = node[kw]
            if not _is_schema(sub):
                raise ContractError(
                    f"'{kw}' must be a schema", path=child(path, kw)
                )
            _check_schema(sub, child(path, kw), is_root=False, refs=refs)

    if "prefixItems" in node:
        arr = node["prefixItems"]
        if not isinstance(arr, list) or not arr:
            raise ContractError(
                "'prefixItems' must be a non-empty array of schemas",
                path=child(path, "prefixItems"),
            )
        for i, sub in enumerate(arr):
            if not _is_schema(sub):
                raise ContractError(
                    "'prefixItems' entries must be schemas",
                    path=child(child(path, "prefixItems"), i),
                )
            _check_schema(
                sub, child(child(path, "prefixItems"), i),
                is_root=False, refs=refs,
            )

    for kw in ("properties", "dependentSchemas"):
        if kw in node:
            obj = node[kw]
            if not isinstance(obj, dict):
                raise ContractError(
                    f"'{kw}' must be an object", path=child(path, kw)
                )
            for name, sub in obj.items():
                if not _is_schema(sub):
                    raise ContractError(
                        f"'{kw}' values must be schemas",
                        path=child(child(path, kw), name),
                    )
                _check_schema(
                    sub, child(child(path, kw), name),
                    is_root=False, refs=refs,
                )
