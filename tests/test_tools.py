from app.tools import calculator, current_time


def calculate(expression: str) -> str:
    return calculator.invoke({"expression": expression})


def test_calculator_supports_basic_arithmetic() -> None:
    assert calculate("(12 + 8) * 3") == "60"
    assert calculate("2 ** 10") == "1024"
    assert calculate("-3 + 5 / 2") == "-0.5"


def test_calculator_handles_errors_without_crashing() -> None:
    assert "除数不能为 0" in calculate("1 / 0")
    assert "不支持的语法" in calculate("__import__('os').system('whoami')")
    assert "不支持该运算符" in calculate("5 & 3")
    assert "指数过大" in calculate("9 ** 999")


def test_calculator_rejects_invalid_input() -> None:
    assert "表达式为空" in calculate("   ")
    assert "表达式过长" in calculate("1+" * 150)


def test_current_time_uses_requested_timezone() -> None:
    utc = current_time.invoke({"timezone": "UTC"})
    shanghai = current_time.invoke({"timezone": "Asia/Shanghai"})
    assert "UTC" in utc
    assert "UTC+08:00" in shanghai


def test_current_time_rejects_unknown_timezone() -> None:
    result = current_time.invoke({"timezone": "Mars/Olympus_Mons"})
    assert "未知时区" in result
