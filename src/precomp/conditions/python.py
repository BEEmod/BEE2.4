"""The Operation result allows executing math on instvars."""
from collections.abc import Callable, Container
from typing import Any, NoReturn
import ast

from precomp import conditions
from srctools import Keyvalues, Vec, Entity, conv_bool
import srctools.logger


COND_MOD_NAME = 'Python'

LOGGER = srctools.logger.get_logger(__name__)

# Functions we allow the result to call.
FUNCS: dict[str, Callable[[str], object]] = {
    'int': int,

    'bool': conv_bool,
    'boolean': conv_bool,

    'string': str,
    'str': str,

    'float': float,

    'vector': Vec.from_str,
    'vec': Vec.from_str,
}

FUNC_GLOBALS = {
    **FUNCS,

    'Vec': Vec,
    # Don't give other globals, they aren't needed.
    '__builtins__': None,
}

BANNED_COMPS = {
    ast.Is: 'is',
    ast.IsNot: 'is not',
    ast.In: 'in',
    ast.NotIn: 'not in',
}


class Checker(ast.NodeVisitor):
    """Scans through the AST, and checks all nodes to ensure they're allowed."""
    def __init__(self, var_names: Container[str]) -> None:
        self.var_names = var_names

    def generic_visit(self, node: ast.AST) -> NoReturn:
        """All other nodes are invalid."""
        raise ValueError(f'A {type(node).__name__} is not permitted!')

    def visit_Name(self, node: ast.Name) -> None:
        """A variable name."""
        if node.id not in self.var_names:
            raise NameError(f'Invalid variable name "{node.id}"')
        if not isinstance(node.ctx, ast.Load):
            raise ValueError('Only reading variables is supported!')

    def safe_visit(self, node: ast.AST) -> None:
        """These are safe, we don't care about them - just contents."""
        super().generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        """and, or, etc"""
        for val in node.values:
            self.visit(val)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        """Math operators, etc."""
        # Don't visit the operator.
        self.visit(node.left)
        self.visit(node.right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        """-a, +a, not a, ~a."""
        self.visit(node.operand)

    def visit_Compare(self, node: ast.Compare) -> None:
        """ < comps etc."""
        try:
            ops = node.ops
        except AttributeError:
            ops = [node.op]  # type: ignore
        for op in ops:
            if isinstance(op, tuple(BANNED_COMPS)):
                raise Exception(f"The {BANNED_COMPS[type(op)]} operator is not allowed!")

        self.visit(node.left)
        for right in node.comparators:
            self.visit(right)

    visit_IfExp = safe_visit  # a if x else b

    # Objects
    visit_Slice = safe_visit  # allow  string[1:2]
    visit_Index = safe_visit  # allow vec['x']
    visit_Num = safe_visit
    visit_Str = safe_visit
    visit_NameConstant = safe_visit  # True, False, None
    visit_Constant = safe_visit


@conditions.make_result('Python', 'Operation')
def res_python_setup(res: Keyvalues) -> conditions.ResultCallable:
    """Apply a function to a fixup."""
    variables: dict[str, Callable[[str], object]] = {}
    variable_order = []
    code = None
    result_var = None
    for child in res:
        if child.name.startswith('$'):
            var_name = child.name[1:]
            try:
                variables[var_name] = FUNCS[child.value.casefold()]
            except KeyError:
                raise Exception(f'Invalid variable type! ({child.value})') from None
            variable_order.append(var_name)
        elif child.name == 'op':
            code = child.value
        elif child.name == 'resultvar':
            result_var = child.value
        else:
            raise Exception(f'Invalid key "{child.real_name}"')
    if not code:
        raise Exception('No operation specified!')
    if not result_var:
        raise Exception('No destination specified!')

    for name in variables:
        if name.startswith('_'):
            raise Exception(f'"{name}" is not permitted as a variable name!')

    # Allow $ in the variable names..
    code = code.replace('$', '')

    # Now process the code to convert it into a function taking variables
    # and returning them.
    # We also need to whitelist operations for security.
    expression = ast.parse(
        code,
        '<bee2_op>',
        mode='eval',
    ).body

    Checker(variable_order).visit(expression)

    args = ast.arguments(
        vararg=None, 
        kwonlyargs=[
            ast.arg(var_name)
            for var_name in variable_order
        ],
        kw_defaults=[], 
        kwarg=None, 
        defaults=[],
        posonlyargs=[],
        args=[],
    )

    func = ast.Module([
            ast.FunctionDef(
                name='_bee2_generated_func',
                args=args,
                body=[ast.Return(expression)],
                decorator_list=[],
                type_params=[],
            ),
        ],
        type_ignores=[],
    )

    # Fill in lineno and col_offset
    ast.fix_missing_locations(func)

    ns: dict[str, Any] = {}
    eval(compile(func, '<bee2_op>', mode='exec'), FUNC_GLOBALS.copy(), ns)
    compiled_func = ns['_bee2_generated_func']
    compiled_func.__name__ = '<bee2_func>'

    def apply_operation(inst: Entity) -> None:
        """Run the operation."""
        result = compiled_func({
            var_name: conv_func(inst.fixup[var_name])
            for var_name, conv_func in variables.items()
        })
        if isinstance(result, bool):
            result = int(result)
        inst.fixup[result_var] = str(result)
    return apply_operation
