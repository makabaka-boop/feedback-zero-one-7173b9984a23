"""JSON Schema 2020-12 子集求值器（核心逻辑全部自写）。

支持关键词见 :mod:`json_contract.precheck`。求值结果除布尔有效性外，
还携带 2020-12 语义下的“有效信息（annotations / evaluated sets）”：

- ``items``:       已被求值/标记的数组下标集合
- ``props``:       已被求值/标记的对象属性名集合

冒泡规则遵循 2020-12 §10/§11：
- anyOf 只汇总成功分支；oneOf 仅在恰好一个成功时汇总该分支；
  allOf 汇总全部分支（任一失败则整体失败）；
- 失败分支与 ``not`` 不贡献；未选中的 then/else 不执行；
- ``$ref`` 的被引用模式的有效信息向外冒泡；
- ``unevaluatedItems`` / ``unevaluatedProperties`` 检查的是同模式内
  其他关键词（含 $ref 与组合器）冒泡上来的集合；
- ``additionalProperties`` 只看同层 ``properties`` 声明的键。
"""

from __future__ import annotations

from typing import Any


class _Result:
    __slots__ = ("valid", "items", "props")

    def __init__(self, valid: bool, items=None, props=None):
        self.valid = valid
        self.items: set[int] = set() if items is None else set(items)
        self.props: set[str] = set() if props is None else set(props)

    @staticmethod
    def ok() -> "_Result":
        return _Result(True)

    @staticmethod
    def fail() -> "_Result":
        return _Result(False)


def evaluate(schema_node: Any, instance: Any, defs: dict) -> bool:
    """对外入口：返回单条 record 的布尔有效性。"""
    return _eval(schema_node, instance, defs).valid


# ---------- 基础断言 ----------


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        # 解析器只产生整数；integer 同时满足 number
        return "integer"
    if isinstance(value, float):  # 防御：正常解析路径不会出现
        return "number" if value != int(value) else "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _check_type(schema_type: Any, instance: Any) -> bool:
    actual = _type_name(instance)
    allowed = schema_type if isinstance(schema_type, list) else [schema_type]
    for name in allowed:
        if name == actual:
            return True
        # integer 也是 number
        if name == "number" and actual == "integer":
            return True
    return False


def _deep_equal(a: Any, b: Any) -> bool:
    """const 用的深度相等：区分 bool 与 int。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if a is None or b is None:
        return a is None and b is None
    if type(a) is not type(b):
        return False
    if isinstance(a, str):
        return a == b
    if isinstance(a, list):
        return len(a) == len(b) and all(
            _deep_equal(x, y) for x, y in zip(a, b)
        )
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(
            _deep_equal(a[k], b[k]) for k in a
        )
    return a == b


# ---------- 主求值 ----------


def _eval(node: Any, instance: Any, defs: dict) -> _Result:
    # 布尔模式
    if node is True:
        return _Result.ok()
    if node is False:
        return _Result.fail()

    result = _Result(True)
    is_object = isinstance(instance, dict)
    is_array = isinstance(instance, list)

    # --- Validation 断言 ---
    if "type" in node and not _check_type(node["type"], instance):
        result.valid = False
    if "const" in node and not _deep_equal(node["const"], instance):
        result.valid = False
    if "required" in node and is_object:
        for name in node["required"]:
            if name not in instance:
                result.valid = False
                break

    # --- $ref：2020-12 中与兄弟关键词并存，引用结果与兄弟结果相与 ---
    if "$ref" in node:
        target_name = node["$ref"][len("#/$defs/"):]
        ref_result = _eval(defs[target_name], instance, defs)
        if not ref_result.valid:
            result.valid = False
        result.items |= ref_result.items
        result.props |= ref_result.props

    # --- 组合器 ---
    if "allOf" in node:
        for sub in node["allOf"]:
            r = _eval(sub, instance, defs)
            if not r.valid:
                result.valid = False
            result.items |= r.items
            result.props |= r.props

    if "anyOf" in node:
        any_ok = False
        for sub in node["anyOf"]:
            r = _eval(sub, instance, defs)
            if r.valid:  # 仅成功分支贡献有效信息
                any_ok = True
                result.items |= r.items
                result.props |= r.props
        if not any_ok:
            result.valid = False

    if "oneOf" in node:
        matched = []
        for sub in node["oneOf"]:
            r = _eval(sub, instance, defs)
            if r.valid:
                matched.append(r)
        if len(matched) != 1:
            result.valid = False
        else:
            result.items |= matched[0].items
            result.props |= matched[0].props

    if "not" in node:
        r = _eval(node["not"], instance, defs)
        if r.valid:
            result.valid = False
        # not 不贡献有效信息

    if "if" in node:
        cond = _eval(node["if"], instance, defs)
        if cond.valid:
            if "then" in node:  # 未选分支不执行
                r = _eval(node["then"], instance, defs)
                if not r.valid:
                    result.valid = False
                result.items |= r.items
                result.props |= r.props
        elif "else" in node:
            r = _eval(node["else"], instance, defs)
            if not r.valid:
                result.valid = False
            result.items |= r.items
            result.props |= r.props

    # --- dependentSchemas（仅对象适用） ---
    if "dependentSchemas" in node and is_object:
        for name, sub in node["dependentSchemas"].items():
            if name in instance:
                r = _eval(sub, instance, defs)
                if not r.valid:
                    result.valid = False
                result.items |= r.items
                result.props |= r.props

    # --- 数组类 ---
    if is_array:
        length = len(instance)

        if "prefixItems" in node:
            for i, sub in enumerate(node["prefixItems"]):
                if i >= length:
                    break
                r = _eval(sub, instance[i], defs)
                result.items.add(i)  # 无论成败，该位置已被求值
                if not r.valid:
                    result.valid = False
                result.items |= r.items
                result.props |= r.props

        if "items" in node:
            start = len(node["prefixItems"]) if "prefixItems" in node else 0
            for i in range(start, length):
                r = _eval(node["items"], instance[i], defs)
                result.items.add(i)
                if not r.valid:
                    result.valid = False
                result.items |= r.items
                result.props |= r.props

        if "contains" in node:
            # 2020-12：contains 的注解为成功匹配的下标列表，
            # 这些下标属于“已求值项”，unevaluatedItems 不再检查它们。
            matched_index: list[int] = []
            for i, item in enumerate(instance):
                r = _eval(node["contains"], item, defs)
                if r.valid:
                    matched_index.append(i)
            if not matched_index:
                result.valid = False
            result.items.update(matched_index)

        if "unevaluatedItems" in node:
            unevaluated = [i for i in range(length) if i not in result.items]
            if unevaluated:
                sub = node["unevaluatedItems"]
                for i in unevaluated:
                    r = _eval(sub, instance[i], defs)
                    result.items.add(i)
                    if not r.valid:
                        result.valid = False
                    result.items |= r.items
                    result.props |= r.props

    # --- 对象类 ---
    if is_object:
        properties = node.get("properties", {})
        matched_by_properties: set[str] = set()

        for name, sub in properties.items():
            if name in instance:
                matched_by_properties.add(name)
                r = _eval(sub, instance[name], defs)
                result.props.add(name)
                if not r.valid:
                    result.valid = False
                result.items |= r.items
                result.props |= r.props

        # additionalProperties 只看同层 properties 的匹配结果
        if "additionalProperties" in node:
            sub = node["additionalProperties"]
            for name, value in instance.items():
                if name in matched_by_properties:
                    continue
                r = _eval(sub, value, defs)
                result.props.add(name)
                if not r.valid:
                    result.valid = False
                result.items |= r.items
                result.props |= r.props

        # unevaluatedProperties 看全部已冒泡的有效信息（含 $ref / 组合）
        if "unevaluatedProperties" in node:
            sub = node["unevaluatedProperties"]
            for name, value in instance.items():
                if name in result.props:
                    continue
                r = _eval(sub, value, defs)
                result.props.add(name)
                if not r.valid:
                    result.valid = False
                result.items |= r.items
                result.props |= r.props

    return result
