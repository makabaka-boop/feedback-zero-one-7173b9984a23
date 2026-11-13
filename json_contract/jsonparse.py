"""严格 JSON 解析器（JSON Grammar, RFC 8259 词法 + 额外约束）。

不使用 json 库解析输入文本（json 库会静默接受重复键、NaN/Infinity、
非整数词法等，无法满足契约），解析为 Python 表示时：

- object -> dict（保留首次出现顺序；重复键直接拒绝）
- array  -> list
- string -> str（含代理对合并；孤立代理拒绝）
- number -> int（仅允许整数字面量，含负零；小数点/指数一律拒绝）
- true/false -> bool；null -> None

拒绝项（均按语法错误处理，路径报 ``$``）：
- 非法 Unicode 转义（含孤立代理、码点超出范围）、未转义控制字符
- 非整数数字词法（1.0、1e3、-0.5 等）及畸形数字
- 重复对象成员
- 非法结构（尾随逗号、尾随垃圾、未闭合容器、非法字面量等）
- BOM、非法 UTF-8
"""

from __future__ import annotations

from .errors import ContractError


class _Parser:
    __slots__ = ("text", "n", "i")

    def __init__(self, text: str):
        self.text = text
        self.n = len(text)
        self.i = 0

    # ---------- 基础工具 ----------

    def _syntax_error(self, msg: str) -> ContractError:
        # 语法错误统一报 $（规范要求），附带文本偏移便于排查
        return ContractError(f"{msg} (offset {self.i})", path="$", syntax=True)

    def _skip_ws(self) -> None:
        text = self.text
        n = self.n
        i = self.i
        while i < n:
            c = text[i]
            if c == " " or c == "\t" or c == "\n" or c == "\r":
                i += 1
            else:
                break
        self.i = i

    def _expect(self, ch: str, what: str) -> None:
        if self.i >= self.n or self.text[self.i] != ch:
            raise self._syntax_error(f"expected {what}")
        self.i += 1

    # ---------- 入口 ----------

    def parse(self):
        self._skip_ws()
        value = self._parse_value()
        self._skip_ws()
        if self.i != self.n:
            raise self._syntax_error("trailing data after JSON value")
        return value

    def _parse_value(self):
        if self.i >= self.n:
            raise self._syntax_error("unexpected end of input")
        c = self.text[self.i]
        if c == "{":
            return self._parse_object()
        if c == "[":
            return self._parse_array()
        if c == '"':
            return self._parse_string()
        if c == "t":
            return self._parse_literal("true", True)
        if c == "f":
            return self._parse_literal("false", False)
        if c == "n":
            return self._parse_literal("null", None)
        if c == "-" or "0" <= c <= "9":
            return self._parse_number()
        raise self._syntax_error(f"unexpected character {c!r}")

    def _parse_literal(self, literal: str, value):
        end = self.i + len(literal)
        if self.text[self.i : end] != literal:
            raise self._syntax_error(f"invalid literal, expected {literal!r}")
        self.i = end
        return value

    # ---------- 对象 ----------

    def _parse_object(self):
        self._expect("{", "'{'")
        result: dict = {}
        self._skip_ws()
        if self.i < self.n and self.text[self.i] == "}":
            self.i += 1
            return result
        while True:
            self._skip_ws()
            if self.i >= self.n or self.text[self.i] != '"':
                raise self._syntax_error("object member name must be a string")
            key = self._parse_string()
            if key in result:
                # 重复成员：整次拒绝
                raise self._syntax_error(f"duplicate object member {key!r}")
            self._skip_ws()
            self._expect(":", "':'")
            self._skip_ws()
            value = self._parse_value()
            result[key] = value
            self._skip_ws()
            if self.i >= self.n:
                raise self._syntax_error("unterminated object")
            ch = self.text[self.i]
            self.i += 1
            if ch == "}":
                return result
            if ch != ",":
                raise self._syntax_error("expected ',' or '}' in object")
            # 逗号后必须还有成员（拒绝尾随逗号）
            self._skip_ws()
            if self.i < self.n and self.text[self.i] == "}":
                raise self._syntax_error("trailing comma in object")

    # ---------- 数组 ----------

    def _parse_array(self):
        self._expect("[", "'['")
        result: list = []
        self._skip_ws()
        if self.i < self.n and self.text[self.i] == "]":
            self.i += 1
            return result
        while True:
            self._skip_ws()
            result.append(self._parse_value())
            self._skip_ws()
            if self.i >= self.n:
                raise self._syntax_error("unterminated array")
            ch = self.text[self.i]
            self.i += 1
            if ch == "]":
                return result
            if ch != ",":
                raise self._syntax_error("expected ',' or ']' in array")
            self._skip_ws()
            if self.i < self.n and self.text[self.i] == "]":
                raise self._syntax_error("trailing comma in array")

    # ---------- 字符串 ----------

    def _parse_string(self) -> str:
        self._expect('"', 'double quote')
        text = self.text
        n = self.n
        out: list[str] = []
        while True:
            if self.i >= n:
                raise self._syntax_error("unterminated string")
            c = text[self.i]
            if c == '"':
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                if self.i >= n:
                    raise self._syntax_error("unterminated escape sequence")
                esc = text[self.i]
                self.i += 1
                simple = {
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "b": "\b",
                    "f": "\f",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }
                if esc in simple:
                    out.append(simple[esc])
                elif esc == "u":
                    cp = self._read_hex4()
                    if 0xD800 <= cp <= 0xDBFF:
                        # 高代理，必须紧跟 \uXXXX 低代理
                        if (
                            self.i + 6 <= n
                            and text[self.i] == "\\"
                            and text[self.i + 1] == "u"
                        ):
                            self.i += 2
                            low = self._read_hex4()
                            if 0xDC00 <= low <= 0xDFFF:
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00)
                                out.append(chr(cp))
                            else:
                                raise self._syntax_error(
                                    "invalid unicode surrogate pair"
                                )
                        else:
                            raise self._syntax_error("lone high surrogate")
                    elif 0xDC00 <= cp <= 0xDFFF:
                        raise self._syntax_error("lone low surrogate")
                    else:
                        out.append(chr(cp))
                else:
                    raise self._syntax_error(f"invalid escape \\{esc}")
            else:
                # 未转义控制字符拒绝（U+0000..U+001F）
                if ord(c) < 0x20:
                    raise self._syntax_error("unescaped control character in string")
                out.append(c)
                self.i += 1

    def _read_hex4(self) -> int:
        text = self.text
        end = self.i + 4
        if end > self.n:
            raise self._syntax_error("incomplete unicode escape")
        value = 0
        for k in range(self.i, end):
            ch = text[k]
            if "0" <= ch <= "9":
                d = ord(ch) - ord("0")
            elif "a" <= ch <= "f":
                d = ord(ch) - ord("a") + 10
            elif "A" <= ch <= "F":
                d = ord(ch) - ord("A") + 10
            else:
                raise self._syntax_error("invalid hex digit in unicode escape")
            value = (value << 4) | d
        self.i = end
        return value

    # ---------- 数字：仅整数字面量 ----------

    def _parse_number(self) -> int:
        text = self.text
        n = self.n
        start = self.i
        i = self.i
        if text[i] == "-":
            i += 1
            if i >= n:
                raise self._syntax_error("invalid number")
        if text[i] == "0":
            i += 1
            # 前导零（01、0.1 之外的形态）非法；0 后只允许结束或非法字符报错
            if i < n and "0" <= text[i] <= "9":
                raise self._syntax_error("leading zeros are not allowed")
        elif "1" <= text[i] <= "9":
            i += 1
            while i < n and "0" <= text[i] <= "9":
                i += 1
        else:
            raise self._syntax_error("invalid number")
        # 契约只收整数字面量：小数点、指数一律拒绝
        if i < n and (text[i] == "." or text[i] == "e" or text[i] == "E"):
            raise self._syntax_error("non-integer number lexical form is rejected")
        token = text[start:i]
        self.i = i
        # Python int 接受 -0
        return int(token)


def loads_strict(raw: bytes | str):
    """严格解析 JSON 输入。

    入参可为 UTF-8 bytes 或已解码 str；拒绝 BOM 与非法 UTF-8。
    任何词法/语法问题抛出 :class:`ContractError`（path 固定为 ``$``）。
    """
    if isinstance(raw, bytes):
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ContractError("UTF-8 BOM is not allowed", path="$", syntax=True)
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ContractError(f"invalid UTF-8: {exc}", path="$", syntax=True)
    elif isinstance(raw, str):
        if raw.startswith("\ufeff"):
            raise ContractError("UTF-8 BOM is not allowed", path="$", syntax=True)
        text = raw
    else:
        raise ContractError("input must be UTF-8 bytes or text", path="$", syntax=True)
    if text == "":
        raise ContractError("empty input", path="$", syntax=True)
    return _Parser(text).parse()
