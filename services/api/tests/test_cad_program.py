import pytest
from app.cad_program import Interpreter, ProgramError, resolve_parameters, validate_source


@pytest.mark.parametrize('source',[
    'import os\nresult = os.getcwd()',
    'result = open("secret").read()',
    'result = __import__("os").system("id")',
    'result = (1).__class__',
    'result = cq.exporters.export(1,"x")',
    'result = eval("1")',
    'result = [x for x in range(10)]',
    'while True:\n    result = 1',
    'params = 1\nresult = params',
    'result = 10 ** 100000',
    'for i in range(100000):\n    result = i',
    'result = math.__dict__',
    'f = math.sin\nresult = f(1)',
    'result = math.sin.__call__(1)',
    'result = cq.Workplane().rarray(1,1,100000,100000)',
])
def test_unsafe_programs_are_rejected(source):
    with pytest.raises(ProgramError): Interpreter().run(source)


def test_parameter_arithmetic_and_bounded_control_flow():
    assert Interpreter({'length':10}).run('total = 0\nfor i in range(4):\n    total = total + params["length"]\nresult = total if total > 20 else 0') == 40


def test_parameter_validation_and_derived_order():
    definitions = [{'name':'width','label':'宽度','default':20,'minimum':1},
                   {'name':'half','label':'半宽','default':10,'expression':'params["width"] / 2'}]
    assert resolve_parameters(definitions,{'width':40}) == {'width':40,'half':20}
    for values in [{'width':-1},{'width':True},{'width':float('nan')},{'half':30},{'unknown':1}]:
        with pytest.raises(ValueError): resolve_parameters(definitions,values)


def test_native_calls_cannot_receive_callable_tokens():
    with pytest.raises(ProgramError,match='回调'):
        Interpreter().run('result = cq.Workplane(math.sin)')


def test_generated_parameter_access_casts_and_profile_concatenation():
    source = '''height = float(params.get("height", 85))
outer = [(0, 0), (20, height)]
inner = [(17, height), (0, 3)]
profile = outer + inner
result = profile'''
    assert Interpreter({'height':90}).run(source) == [(0, 0), (20, 90.), (17, 90.), (0, 3)]
    assert Interpreter().run('result = int(3.9) + len((1,2))') == 5


@pytest.mark.parametrize('source', [
    'result = float("nan")', 'result = int("4")',
    'result = params.update(1)', 'result = params.pop("height")',
    'result = cq.Workplane((math.sin,))',
    'points = [0]\nfor i in range(10):\n    points = points + points\nresult = points',
])
def test_new_conveniences_keep_type_and_size_limits(source):
    with pytest.raises(ProgramError): Interpreter({'height':85}).run(source)


def test_all_syntax_issues_are_reported_before_native_execution():
    source = '''body = cq.Workplane().box(10,10,10)
try:
    body = body.edges().fillet(1)
except:
    pass
result = str(body)'''
    # No CadQuery module is supplied: runtime evaluation would fail on line 1.
    with pytest.raises(ProgramError) as caught: Interpreter().run(source)
    message = str(caught.value)
    assert '尚未执行几何建模' in message
    assert '第 2 行' in message and 'try/except' in message
    assert '第 6 行' in message and 'str' in message
    with pytest.raises(ProgramError): validate_source('if False:\n    import os\nresult = 1')
