import ast
import operator

# Supported operators mapping
ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def eval_expr(node):
    """
    Evaluate an AST node representing a mathematical expression safely.
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")
    elif isinstance(node, ast.BinOp):
        left = eval_expr(node.left)
        right = eval_expr(node.right)
        op_type = type(node.op)
        if op_type in ALLOWED_OPERATORS:
            return ALLOWED_OPERATORS[op_type](left, right)
        else:
            raise ValueError(f"Unsupported binary operator: {op_type}")
    elif isinstance(node, ast.UnaryOp):
        operand = eval_expr(node.operand)
        op_type = type(node.op)
        if op_type in ALLOWED_OPERATORS:
            return ALLOWED_OPERATORS[op_type](operand)
        else:
            raise ValueError(f"Unsupported unary operator: {op_type}")
    else:
        raise ValueError(f"Unsupported expression node: {type(node)}")


def solve_math(expression: str) -> float:
    """
    Parse and evaluate a mathematical expression string safely.
    Returns the numeric result.
    """
    try:
        # Parse the expression into an AST
        # mode='eval' ensures it's a single expression
        tree = ast.parse(expression, mode="eval")
        # Evaluate the body of the Expression node
        result = eval_expr(tree.body)
        return float(result)
    except Exception as e:
        raise ValueError(f"Failed to evaluate expression '{expression}': {e}")
