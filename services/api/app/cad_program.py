"""A small interpreter for modelling expressions. Never executes Python bytecode.

Only explicit receiver-type/method pairs can cross into CadQuery. In particular,
attribute lookup, callbacks, imports, exporters and Python introspection are not
available to a model-generated program.
"""
from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Parameter(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    name: str = Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,63}$')
    label: str = Field(min_length=1, max_length=100)
    type: Literal['number', 'integer', 'boolean', 'enum'] = 'number'
    default: Any
    unit: str = Field(default='mm', max_length=12)
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] = Field(default_factory=list, max_length=50)
    expression: str | None = Field(default=None, max_length=500)

    @model_validator(mode='after')
    def limits(self):
        if self.type == 'enum' and not self.options: raise ValueError('枚举参数缺少选项')
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError('参数最小值大于最大值')
        if any(v is not None and not math.isfinite(v) for v in (self.minimum, self.maximum)):
            raise ValueError('参数范围必须为有限数值')
        return self


class CadBuildRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: str | None = Field(default=None, max_length=60000)
    parameter_definitions: list[Parameter] | None = Field(default=None, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)
    title: str = Field(default='CAD 模型', max_length=150)
    canvas_node_id: str | None = None
    base_revision: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    expected_dimensions: dict[str, float] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, max_length=150)


@dataclass(frozen=True)
class Module:
    name: str


@dataclass(frozen=True)
class Call:
    receiver: Any
    name: str


WORKPLANE_METHODS = set('workplane transformed center move moveTo line lineTo hLine vLine hLineTo vLineTo polarLine polarLineTo polyline close circle ellipse rect polygon slot2D threePointArc radiusArc tangentArcPoint spline box sphere cylinder cone wedge extrude twistExtrude revolve loft sweep cut cutBlind cutThruAll union intersect hole cboreHole cskHole fillet chamfer shell faces edges vertices wires solids all val vals size findSolid translate rotate mirror mirrorX mirrorY rarray polarArray pushPoints tag workplaneFromTagged add toPending'.split())
SHAPE_METHODS = set('translate rotate mirror fuse cut intersect fillet chamfer clean'.split())
MATH_FUNCTIONS = {'sin', 'cos', 'tan', 'sqrt', 'radians', 'degrees', 'floor', 'ceil', 'atan2', 'fabs'}
BUILTINS = {'range', 'min', 'max', 'abs', 'round', 'float', 'int', 'len'}


class ProgramError(ValueError):
    pass


def validate_source(source):
    """Check the entire syntax before any native geometry call, including dead branches."""
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise ProgramError(f'程序语法检查失败：第 {error.lineno} 行：{error.msg}') from error
    if len(list(ast.walk(tree))) > 5000: raise ProgramError('建模程序过长')
    allowed = {ast.Module, ast.Import, ast.alias, ast.Assign, ast.Expr, ast.If, ast.For, ast.Assert,
               ast.Constant, ast.Name, ast.List, ast.Tuple, ast.UnaryOp, ast.BinOp,
               ast.Compare, ast.IfExp, ast.Subscript, ast.Attribute, ast.Call, ast.keyword,
               ast.Load, ast.Store, ast.UAdd, ast.USub, ast.Not, ast.Add, ast.Sub,
               ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.Eq, ast.NotEq, ast.Lt,
               ast.LtE, ast.Gt, ast.GtE}
    issues = []

    class Validator(ast.NodeVisitor):
        def generic_visit(self, node):
            issue = None
            if type(node) not in allowed:
                issue = f'不支持 {type(node).__name__}'
                if isinstance(node, ast.Try): issue += '；请移除 try/except，让宿主返回建模错误'
            elif isinstance(node, ast.Import) and any((a.name, a.asname) not in {('cadquery', 'cq'), ('math', None)} for a in node.names):
                issue = '只允许 import cadquery as cq 和 import math'
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in BUILTINS:
                issue = f'不允许调用 {node.func.id}；只能调用登记的 CadQuery 方法和数值函数'
            elif isinstance(node, ast.Compare) and len(node.ops) != 1:
                issue = '不支持链式比较；请拆成嵌套 if'
            if issue:
                issues.append(f'第 {getattr(node, "lineno", 0)} 行：{issue}')
                return
            super().generic_visit(node)

    Validator().visit(tree)
    if issues: raise ProgramError('程序语法检查失败（尚未执行几何建模）：' + '；'.join(issues[:12]))
    return tree


class Interpreter:
    def __init__(self, parameters=None, cq=None):
        self.cq = cq
        self.env = {'params': parameters or {}, 'cq': Module('cq'), 'math': Module('math')}
        self.steps = 0
        self.line = 0

    def tick(self, node):
        self.steps += 1
        self.line = getattr(node, 'lineno', self.line)
        if self.steps > 12000: raise ProgramError('建模程序超过复杂度限制')

    @staticmethod
    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e12:
            raise ProgramError('运算需要有限数值，绝对值不得超过 1e12')
        return value

    def expr(self, node):
        self.tick(node)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float, str, bool, type(None)):
            if isinstance(node.value, str) and len(node.value) > 1000: raise ProgramError('字符串过长')
            if type(node.value) in (int, float): self.number(node.value)
            return node.value
        if isinstance(node, ast.Name):
            if node.id in self.env: return self.env[node.id]
            raise ProgramError(f'未定义变量：{node.id}')
        if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) <= 512:
            values = [self.expr(x) for x in node.elts]
            return tuple(values) if isinstance(node, ast.Tuple) else values
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            value = self.expr(node.operand)
            if isinstance(node.op, ast.Not): return not self.truth(value)
            return self.number(value) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp):
            left, right = self.expr(node.left), self.expr(node.right)
            if isinstance(node.op, ast.Add) and type(left) in (list, tuple) and type(right) is type(left):
                if len(left) + len(right) > 512: raise ProgramError('点列表最多 512 项')
                return left + right
            left, right = self.number(left), self.number(right)
            ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
            if type(node.op) not in ops: raise ProgramError('不支持的数值运算')
            if isinstance(node.op, ast.Pow) and abs(right) > 8: raise ProgramError('指数绝对值不得超过 8')
            return self.number(ops[type(node.op)](left, right))
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b = self.expr(node.left), self.expr(node.comparators[0])
            if type(a) not in (str, bool, int, float) or type(b) not in (str, bool, int, float): raise ProgramError('比较只接受参数值')
            ops = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
            if type(node.ops[0]) in ops: return ops[type(node.ops[0])](a, b)
        if isinstance(node, ast.IfExp): return self.expr(node.body if self.truth(self.expr(node.test)) else node.orelse)
        if isinstance(node, ast.Subscript):
            value, index = self.expr(node.value), self.expr(node.slice)
            if type(value) is dict and type(index) is str and index in value: return value[index]
            if type(value) in (list, tuple) and type(index) is int and -len(value) <= index < len(value): return value[index]
            raise ProgramError('只能索引已有参数或列表元素')
        if isinstance(node, ast.Attribute):
            receiver = self.expr(node.value)
            if node.attr.startswith('_'): raise ProgramError('禁止访问内部属性')
            if isinstance(receiver, Module) and receiver.name == 'math' and node.attr in {'pi', 'e'}: return getattr(math, node.attr)
            return Call(receiver, node.attr)
        if isinstance(node, ast.Call):
            if len(node.args) + len(node.keywords) > 32 or any(k.arg is None for k in node.keywords): raise ProgramError('调用参数无效')
            args = [self.expr(x) for x in node.args]
            kwargs = {k.arg: self.expr(k.value) for k in node.keywords}
            if isinstance(node.func, ast.Name) and node.func.id in BUILTINS:
                if kwargs: raise ProgramError('数值函数只接受位置参数')
                if node.func.id == 'len':
                    if len(args) != 1 or type(args[0]) not in (list, tuple, str): raise ProgramError('len 只接受点列表或字符串')
                    return len(args[0])
                if node.func.id in {'float', 'int'}:
                    if len(args) != 1: raise ProgramError('类型转换只接受一个有限数值')
                    value = self.number(args[0])
                    return self.number(float(value) if node.func.id == 'float' else int(value))
                for arg in args: self.number(arg)
                if node.func.id == 'range':
                    value = range(*args)
                    if len(value) > 128: raise ProgramError('循环最多 128 次')
                    return list(value)
                return self.number({'min': min, 'max': max, 'abs': abs, 'round': round}[node.func.id](*args))
            target = self.expr(node.func)
            if not isinstance(target, Call): raise ProgramError('只允许已登记的建模函数')
            # Never pass a callable, module or attribute token into native code.
            def check_arg(value):
                if isinstance(value, (Module, Call)) or callable(value): raise ProgramError('禁止回调和动态属性')
                if type(value) in (list, tuple):
                    for child in value: check_arg(child)
            for value in [*args, *kwargs.values()]: check_arg(value)
            receiver, name = target.receiver, target.name
            if type(receiver) is dict and name == 'get':
                if kwargs or len(args) not in (1, 2) or type(args[0]) is not str: raise ProgramError('params.get 只接受参数名和可选默认值')
                return receiver.get(*args)
            if name in {'rarray', 'polarArray', 'polygon'}:
                positions = {'rarray': [(2, 'xCount'), (3, 'yCount')], 'polarArray': [(3, 'count')], 'polygon': [(0, 'nSides')]}[name]
                count = 1
                for index, key in positions:
                    value = kwargs.get(key, args[index] if len(args) > index else 1)
                    if type(value) is not int or not 1 <= value <= 256: raise ProgramError('阵列或多边形数量必须为 1–256')
                    count *= value
                if count > 512: raise ProgramError('阵列最多 512 项')
            if isinstance(receiver, Module):
                if receiver.name == 'math' and name in MATH_FUNCTIONS:
                    for arg in args: self.number(arg)
                    if kwargs: raise ProgramError('数学函数不接受关键字参数')
                    return self.number(getattr(math, name)(*args))
                if self.cq and receiver.name == 'cq' and name in {'Workplane', 'Vector', 'Location', 'Assembly', 'Color'}:
                    return getattr(self.cq, name)(*args, **kwargs)
            elif self.cq:
                allowed = WORKPLANE_METHODS if isinstance(receiver, self.cq.Workplane) else SHAPE_METHODS if isinstance(receiver, self.cq.Shape) else {'add'} if isinstance(receiver, self.cq.Assembly) else set()
                if name in allowed: return getattr(receiver, name)(*args, **kwargs)
            raise ProgramError(f'不允许调用 {name}')
        raise ProgramError(f'不支持语法：{type(node).__name__}')

    @staticmethod
    def truth(value):
        if type(value) not in (bool, int, float, str): raise ProgramError('条件必须是参数值')
        return bool(value)

    def assign(self, target, value):
        if not isinstance(target, ast.Name) or target.id.startswith('_') or target.id in {'cq', 'math', 'params'} | BUILTINS:
            raise ProgramError('只允许给普通局部变量赋值')
        if isinstance(value, (Call, Module)): raise ProgramError('不能保存函数或模块引用')
        self.env[target.id] = value

    def statements(self, body):
        for node in body:
            self.tick(node)
            if isinstance(node, ast.Import) and all((a.name, a.asname) in {('cadquery', 'cq'), ('math', None)} for a in node.names): continue
            if isinstance(node, ast.Assign) and len(node.targets) == 1: self.assign(node.targets[0], self.expr(node.value))
            elif isinstance(node, ast.Expr): self.expr(node.value)
            elif isinstance(node, ast.Assert):
                if not self.truth(self.expr(node.test)):
                    message = self.expr(node.msg) if node.msg else '尺寸关系不满足建模要求'
                    if type(message) is not str: raise ProgramError('参数检查信息必须为字符串')
                    raise ProgramError(f'参数约束失败：{message}')
            elif isinstance(node, ast.If): self.statements(node.body if self.truth(self.expr(node.test)) else node.orelse)
            elif isinstance(node, ast.For) and not node.orelse:
                values = self.expr(node.iter)
                if type(values) not in (list, tuple) or len(values) > 128: raise ProgramError('循环只能遍历不超过 128 项的列表')
                for value in values:
                    self.assign(node.target, value)
                    self.statements(node.body)
            else: raise ProgramError(f'不支持语句：{type(node).__name__}')

    def run(self, source):
        tree = validate_source(source)
        try:
            self.statements(tree.body)
            result = self.env.get('result')
            if result is None: raise ProgramError('程序必须将最终模型赋给 result')
            return result
        except Exception as error:
            raise ProgramError(f'第 {self.line} 行：{error}') from error


def resolve_parameters(definitions, supplied):
    definitions = [Parameter.model_validate(d) for d in definitions]
    names = [d.name for d in definitions]
    if len(set(names)) != len(names): raise ProgramError('参数名重复')
    if set(supplied) - set(names): raise ProgramError('包含未知参数')
    values = {}
    for definition in definitions:
        if definition.expression:
            if definition.name in supplied: raise ProgramError(f'{definition.label} 是只读派生参数')
            value = Interpreter(values).expr(ast.parse(definition.expression, mode='eval').body)
        else: value = supplied.get(definition.name, definition.default)
        valid = (definition.type == 'number' and type(value) in (int, float) or definition.type == 'integer' and type(value) is int or definition.type == 'boolean' and type(value) is bool or definition.type == 'enum' and type(value) is str and value in definition.options)
        if not valid: raise ProgramError(f'{definition.label} 的类型或选项不正确')
        if definition.type in {'number', 'integer'}:
            Interpreter.number(value)
            if definition.minimum is not None and value < definition.minimum or definition.maximum is not None and value > definition.maximum:
                raise ProgramError(f'{definition.label} 超出允许范围')
        values[definition.name] = value
    return values
