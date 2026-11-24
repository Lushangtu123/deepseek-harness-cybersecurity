"""Record narrowly scoped Python eval guard evidence without executing source."""
import argparse
import ast
import json
import re

MAX_BYTES = 1048576
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')


def name_is(node, name):
    return isinstance(node, ast.Name) and node.id == name


def canonical_flask_request(tree):
    imports = [
        alias
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == 'flask'
        for alias in node.names
        if alias.name == 'request' and alias.asname is None
    ]
    if len(imports) != 1:
        return False
    return has_unambiguous_bindings(tree, {'request', 'eval'}, imports)


def has_unambiguous_bindings(tree, protected, imports):
    for node in ast.walk(tree):
        # Generic annotation scopes need separate name-resolution modelling.
        if getattr(node, 'type_params', None):
            return False
        if isinstance(node, ast.alias) and not any(node is allowed for allowed in imports):
            if (node.asname or node.name.split('.')[0]) in protected | {'*'}:
                return False
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in protected:
            return False
        if isinstance(node, ast.arg) and node.arg in protected:
            return False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name in protected:
            return False
        if isinstance(node, ast.MatchMapping) and node.rest in protected:
            return False
    return True


def request_assignment(node, name):
    match node:
        case ast.Assign(targets=[target], value=ast.Call(
            func=ast.Attribute(value=ast.Attribute(value=request, attr='args'), attr='get'),
            args=[ast.Constant(value=str())], keywords=[]
        )):
            return name_is(target, name) and name_is(request, 'request')
    return False


def guard_literals(test, name):
    match test:
        case ast.Compare(left=left, ops=[ast.In()], comparators=[ast.Tuple(elts=elements)]) if name_is(left, name):
            candidates = elements
        case _:
            candidates = []
            branches = test.values if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) else [test]
            for branch in branches:
                match branch:
                    case ast.Compare(left=left, ops=[ast.Eq()], comparators=[value]) if name_is(left, name):
                        candidates.append(value)
                    case _:
                        return None
    if not 1 <= len(candidates) <= 16:
        return None
    if any(not isinstance(node, ast.Constant) or not isinstance(node.value, str)
           or not IDENTIFIER.fullmatch(node.value) for node in candidates):
        return None
    return len({node.value for node in candidates})


def direct_eval(statement, line):
    match statement:
        case ast.Return(value=call) | ast.Expr(value=call) | ast.Assign(targets=[ast.Name()], value=call):
            match call:
                case ast.Call(func=ast.Name(id='eval'), args=[ast.Name(id=name)], keywords=[]) if call.lineno == line:
                    return name
    return None


def unique_dynamic_execution(tree, statement, call):
    """Line-only scanner anchors cannot distinguish multiple dynamic executions."""
    first = min(statement.lineno, call.lineno)
    last = max(statement.end_lineno, call.end_lineno)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and (isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec', 'compile'}
                  or isinstance(node.func, ast.Attribute) and node.func.attr in {'eval', 'exec', 'compile'})
             and node.lineno <= last and node.end_lineno >= first]
    return len(calls) == 1 and calls[0] is call


def review_eval_guard(source, line):
    """Return conditional syntactic evidence. Findings retain their disposition."""
    if type(line) is not int or line < 1 or len(source.encode('utf-8')) > MAX_BYTES:
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    if not canonical_flask_request(tree):
        return None
    calls_at_line = [
        node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and node.lineno == line and name_is(node.func, 'eval')
    ]
    if len(calls_at_line) != 1:
        return None
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        for assignment, guard in zip(function.body, function.body[1:]):
            if not isinstance(guard, ast.If):
                continue
            name = direct_eval(guard.body[0], line)
            if not name or not request_assignment(assignment, name):
                continue
            if not unique_dynamic_execution(tree, guard.body[0], calls_at_line[0]):
                continue
            if any(isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names
                   for node in ast.walk(function)):
                continue
            count = guard_literals(guard.test, name)
            if count is not None:
                return {
                    'observation': 'literal-identifier-guard-observed',
                    'assignmentLine': assignment.lineno, 'guardLine': guard.lineno,
                    'evalLine': line, 'literalCount': count, 'disposition': 'unverified',
                }
    return None



def string_guard_exits(body, variable):
    statements = body
    if len(body) == 2:
        match body[0]:
            case ast.AugAssign(target=ast.Name(id=target), op=ast.Add(), value=ast.Constant(value=str())) if target != variable:
                if not isinstance(body[1], ast.Return) or not name_is(body[1].value, target):
                    return False
                return True
            case _:
                return False
    if len(statements) != 1:
        return False
    match statements[0]:
        case ast.Return(value=ast.Constant(value=str())):
            return True
        case _:
            return False


def review_plain_string_guard(source, line):
    """Record a terminating string-shape check. Runtime string semantics remain unverified."""
    if type(line) is not int or line < 1 or len(source.encode('utf-8')) > MAX_BYTES:
        return None
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    if not canonical_flask_request(tree) or not has_unambiguous_bindings(tree, {'exec'}, []):
        return None
    observations = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for index, (guard, following) in enumerate(zip(function.body,function.body[1:])):
            if not isinstance(guard,ast.If) or guard.orelse:
                continue
            statement = following.body[0] if isinstance(following,ast.Try) else following
            match statement:
                case ast.Return(value=value) | ast.Expr(value=value) | ast.Assign(targets=[ast.Name()],value=value) | ast.AugAssign(target=ast.Name(),op=ast.Add(),value=value):
                    call = value
                case _:
                    continue
            match call:
                case ast.Call(func=ast.Name(id=sink),args=[ast.Name(id=variable)],keywords=[]) if sink in {'eval','exec'}:
                    pass
                case _:
                    continue
            if line not in {statement.lineno,call.lineno}:
                continue
            if not unique_dynamic_execution(tree, statement, call):
                continue
            if index == 0:
                continue
            assignment = function.body[index-1]
            if not isinstance(assignment, ast.Assign) or len(assignment.targets) != 1 or not name_is(assignment.targets[0], variable):
                continue
            stores = [node for node in ast.walk(function) if isinstance(node, ast.Name)
                      and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == variable]
            if len(stores) != 1:
                continue
            if any(isinstance(node,(ast.Global,ast.Nonlocal)) and variable in node.names for node in ast.walk(function)):
                continue
            expected = ast.parse(
                f"not {variable}.startswith(\"'\") or not {variable}.endswith(\"'\") or \"'\" in {variable}[1:-1]",
                mode='eval',
            ).body
            if ast.dump(guard.test)!=ast.dump(expected) or not string_guard_exits(guard.body,variable):
                continue
            observations.append({
                'observation':'plain-string-guard-observed', 'guardLine':guard.lineno,
                'executionLine':call.lineno, 'sink':sink, 'disposition':'unverified',
            })
    if len(observations)==1:
        return observations[0]
    return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file')
    parser.add_argument('line', type=int)
    args = parser.parse_args()
    try:
        with open(args.file, 'rb') as source:
            data = source.read(MAX_BYTES + 1)
        result = review_eval_guard(data.decode('utf-8'), args.line) if len(data) <= MAX_BYTES else None
    except (OSError, UnicodeError):
        result = None
    print(json.dumps(result))
