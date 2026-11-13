# 组合契约采集入湖校验后端

从零实现的 JSON Schema 2020-12 子集校验服务：输入一份 UTF-8 JSON
（仅含 `schema` 与 `records` 数组），按 records 原序输出布尔数组；
空批输出 `[]`；不合模式的记录为 `false`；词法/语法/模式预检问题整次拒绝。
核心求值全部自写，仅使用 Python 标准库，不依赖任何校验引擎。

## 目录结构

```
cli.py                     命令行入口（原子替换输出，失败保留旧文件）
run_acceptance.py          一键验收
json_contract/
  jsonparse.py             自写严格 JSON 解析器（重复键/代理/整数词法/结构）
  precheck.py              全模式预检（关键词白名单、参数形状、$ref、无环）
  evaluator.py             2020-12 子集求值器（布尔结果 + 有效信息冒泡）
  contract.py              对外主入口 validate_batch / process_text
  paths.py                 JSON 路径渲染（$、.key、[i] 零基下标）
  errors.py                ContractError（path / index / syntax）
tests/
  test_rejections.py       独立拒绝语料（59 项，不依赖对照库）
  test_edge_cases.py       边缘行为（预检覆盖、编码、原序、深度引用链）
  test_semantics.py        语义单元（含成熟库对照，25 组）
  test_differential.py     差分模糊（220 模式 / 543 对）
  test_fuzz_large.py       多种子大规模差分（5 种子 / 8922 对）
```

## 使用

```bash
# 成功：输出文件被原子替换为布尔数组
python3 -I cli.py input.json output.json
# 失败：退出码 2，错误 JSON 写 stderr，旧 output.json 原样保留
```

输入示例（题目范例）：

```json
{"schema":{"contains":{"const":1},"unevaluatedItems":false},
 "records":[[1,1],[1,2],[]]}
```

输出：

```json
[true,false,false]
```

## 支持范围

- Core（§10）：`$defs`（仅根、名称 `[A-Za-z]+`）、`$ref`（仅 `#/$defs/名称`、
  目标须存在、定义引用图须无环）。
- Validation（§11）：仅 `type`、`const`、`required`，参数按标准形状。
- Applicator（§11）：除 `patternProperties`、`propertyNames` 外全部：
  `allOf` `anyOf` `oneOf` `not` `if/then/else` `dependentSchemas`
  `prefixItems` `items` `contains` `unevaluatedItems`
  `properties` `additionalProperties` `unevaluatedProperties`。
- 布尔模式（`true`/`false`）。
- 其余关键词（含 `$schema`、`enum`、`minimum` 等）整次拒绝。

### 有效信息（annotation）冒泡规则

- `anyOf` 只汇总成功分支；失败分支与 `not` 不贡献；未选中的 `then/else` 不执行。
- `oneOf` 仅在恰好一个分支成功时汇总该分支；`allOf` 汇总全部分支。
- `$ref` 被引用模式的有效信息向外冒泡，并与兄弟关键词结果相与。
- 剩余项检查（`unevaluatedItems`/`unevaluatedProperties`）消费同模式内
  所有关键词（含引用与组合）冒泡的集合；
  `additionalProperties` 只看同层 `properties` 的匹配键。
- `contains` 成功匹配的下标计入“已求值项”（2020-12 annotation 语义）。

## 整次拒绝规则（多错任选，报 JSON 路径与零基下标；语法错误报 `$`）

- 重复对象成员、非法 Unicode（孤立代理等）、非整数数字词法（`1.0`/`1e3`…）、
  非法结构（尾随逗号/尾随垃圾/未闭合等）、非法 UTF-8/BOM。
- 预检遍历**全部**模式，包括从未被引用的 `$defs` 与不可达分支。
- 非法引用、定义环、`$defs` 越权或命名非法、未支持关键词、参数形状非法。

## 验收

```bash
# 独立套件（无第三方依赖；交付程序始终以 -I 运行）
python3 -I tests/test_rejections.py
python3 -I tests/test_edge_cases.py

# 差分套件需要成熟 2020-12 库 jsonschema（仅测试期对照，不进入运行时）
PYTHONPATH=/path/to/libs python3 run_acceptance.py
```

差分语料只使用双方合法交集：实例数字均为整数字面量，模式仅用本实现支持的
关键词与受约束的 `$ref/$defs`（DAG）。当前结果：拒绝 59 项、语义 25 组、
差分 543 对 + 大规模 8922 对，全部与成熟库一致。
