import pytest
from src.services.math_solver import solve_math


def test_solve_math_basic_operations():
    assert solve_math("1 + 1") == 2.0
    assert solve_math("10 - 5") == 5.0
    assert solve_math("3 * 4") == 12.0
    assert solve_math("10 / 2") == 5.0


def test_solve_math_complex_operations():
    assert solve_math("2 ** 3") == 8.0
    assert solve_math("-5 + 10") == 5.0
    assert solve_math("2 * (3 + 4)") == 14.0
    assert solve_math("10 / (2 * 5)") == 1.0


def test_solve_math_floats():
    assert solve_math("1.5 + 2.5") == 4.0
    assert solve_math("10.0 / 3") == pytest.approx(3.33333333333)


def test_solve_math_invalid_expressions():
    with pytest.raises(ValueError):
        solve_math("import os; os.system('ls')")

    with pytest.raises(ValueError):
        solve_math("1 + 'a'")

    with pytest.raises(ValueError):
        solve_math("1 = 1")

def test_solve_math_unsupported_operators():
    with pytest.raises(ValueError, match="Unsupported binary operator"):
        solve_math("1 ^ 1")

    with pytest.raises(ValueError, match="Unsupported unary operator"):
        solve_math("~1")

def test_solve_math_unsupported_node():
    with pytest.raises(ValueError, match="Unsupported expression node"):
        solve_math("[1, 2]")
