"""Small, deterministic tools exposed to the LangChain agent."""

from __future__ import annotations

import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool

_MAX_EXPRESSION_LENGTH = 200
_MAX_ABS_EXPONENT = 100

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def _format_number(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def _evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("只支持数字常量")
        return node.value

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _BINARY_OPERATORS:
            raise ValueError("不支持该运算符")
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if op_type is ast.Pow and abs(right) > _MAX_ABS_EXPONENT:
            raise ValueError("指数过大")
        return _BINARY_OPERATORS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _UNARY_OPERATORS:
            raise ValueError("不支持该一元运算符")
        return _UNARY_OPERATORS[op_type](_evaluate(node.operand))

    raise ValueError("表达式中包含不支持的语法")


@tool
def calculator(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression.

    Supports +, -, *, /, //, %, ** and parentheses. Use this for any math
    question instead of calculating mentally.

    Args:
        expression: A math expression such as "(12 + 8) * 3".
    """
    expression = expression.strip()
    if not expression:
        return "计算错误：表达式为空"
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        return "计算错误：表达式过长"

    try:
        tree = ast.parse(expression, mode="eval")
        result = _evaluate(tree)
        if isinstance(result, complex):
            return "计算错误：结果不是实数"
        if isinstance(result, float) and (result != result or abs(result) == float("inf")):
            return "计算错误：结果无效"
        return _format_number(result)
    except ZeroDivisionError:
        return "计算错误：除数不能为 0"
    except (SyntaxError, ValueError, TypeError, OverflowError) as exc:
        return f"计算错误：{exc}"


@tool
def current_time(timezone: str = "Asia/Shanghai") -> str:
    """Get the current date and time for an IANA timezone.

    Args:
        timezone: IANA timezone name, e.g. "Asia/Shanghai" or "UTC".
    """
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        return f"时区错误：未知时区 {timezone!r}，请使用如 Asia/Shanghai 的名称"
    except ValueError as exc:
        return f"时区错误：{exc}"

    offset = now.strftime("%z")
    offset_text = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    weekday = _WEEKDAYS[now.weekday()]
    return f"{now:%Y-%m-%d %H:%M:%S} {weekday} ({offset_text})"


TOOLS = [calculator, current_time]
