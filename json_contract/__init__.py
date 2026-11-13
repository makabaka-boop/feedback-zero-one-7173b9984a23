"""组合契约采集入湖校验后端。

纯标准库实现，核心求值自写，不依赖任何 JSON Schema 校验引擎。

模块划分：
- errors:   统一的契约错误类型
- jsonparse: 自写严格 JSON 词法/语法解析器（拒绝重复成员、非法 Unicode、非整数词法等）
- precheck:  全部模式的预检（关键词白名单、参数形状、引用存在性、定义图无环）
- evaluator: JSON Schema 2020-12 子集求值器（布尔结果 + 有效信息冒泡）
- contract:  对外主入口
"""

from .contract import validate_batch, ContractError

__all__ = ["validate_batch", "ContractError"]
