"""Record a direct Python import-to-execution flow without importing the project."""
import argparse
import ast
import json
from pathlib import Path

from eval_guard_review import (
    IDENTIFIER, MAX_BYTES, canonical_flask_request, has_unambiguous_bindings,
    name_is, request_assignment,
)


def direct_call(statement, line=None):
    match statement:
        case ast.Return(value=call) | ast.Expr(value=call) | ast.Assign(targets=[ast.Name()], value=call):
            match call:
                case ast.Call(func=ast.Name(id=function), args=[ast.Name(id=argument)], keywords=[]):
                    if line is None or call.lineno == line:
                        return function, argument
    return None


def target_sink(tree, imported):
    match tree.body:
        case [ast.FunctionDef(name=name, args=args, decorator_list=[], body=[statement])] if name == imported:
            if (args.posonlyargs or len(args.args) != 1 or args.vararg or args.kwarg
                    or args.kwonlyargs or args.defaults):
                return None
            if args.args[0].annotation is not None or tree.body[0].returns is not None:
                return None
            direct = direct_call(statement, statement.lineno)
            if direct and direct[0] in {'eval', 'exec'} and direct[1] == args.args[0].arg:
                if has_unambiguous_bindings(tree, {direct[0]}, []):
                    return tree.body[0].lineno, statement.lineno, direct[0]
    return None


def request_call_sites(tree, line=None):
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        external = {name for node in ast.walk(function) if isinstance(node, (ast.Global, ast.Nonlocal))
                    for name in node.names}
        for assignment, statement in zip(function.body, function.body[1:]):
            call = direct_call(statement, line)
            if call and call[1] not in external and request_assignment(assignment, call[1]):
                yield assignment, statement, call[0]


def discover_import_calls(source, modules):
    """Yield candidate module and line pairs; verification remains a separate step."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return
    imported = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in modules:
            for alias in node.names:
                if alias.name != '*':
                    imported.setdefault(alias.asname or alias.name, set()).add(node.module)
    if not imported or not canonical_flask_request(tree):
        return
    for _, statement, binding in request_call_sites(tree):
        for module in sorted(imported.get(binding, ())):
            yield module, statement.value.lineno


def review_import_flow(caller, module, callee, line):
    """Return syntactic evidence conditional on resolving the explicit sibling module."""
    if type(line) is not int or line < 1 or not IDENTIFIER.fullmatch(module):
        return None
    if any(len(source.encode('utf-8')) > MAX_BYTES for source in (caller, callee)):
        return None
    try:
        caller_tree, callee_tree = ast.parse(caller), ast.parse(callee)
    except (SyntaxError, ValueError, RecursionError):
        return None
    if not canonical_flask_request(caller_tree):
        return None
    for assignment, _, binding in request_call_sites(caller_tree, line):
        imports = [
            (node, alias)
            for node in caller_tree.body
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module
            for alias in node.names if (alias.asname or alias.name) == binding
        ]
        if len(imports) != 1:
            continue
        declaration, alias = imports[0]
        if not has_unambiguous_bindings(caller_tree, {binding}, [alias]):
            continue
        sink = target_sink(callee_tree, alias.name)
        if sink:
            definition_line, sink_line, sink_name = sink
            return {
                'observation': 'direct-import-execution-flow-observed',
                'sourceLine': assignment.lineno, 'importLine': declaration.lineno,
                'callLine': line, 'definitionLine': definition_line, 'sinkLine': sink_line,
                'sink': sink_name, 'disposition': 'unverified',
            }
    return None


def read_source(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected an ordinary Python source file')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Source exceeds byte limit')
    return data.decode('utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('caller', type=Path)
    parser.add_argument('callee', type=Path)
    parser.add_argument('line', type=int)
    args = parser.parse_args()
    result = None
    try:
        if (args.caller.suffix == args.callee.suffix == '.py'
                and args.caller.parent.resolve() == args.callee.parent.resolve()
                and args.caller.resolve() != args.callee.resolve()):
            result = review_import_flow(read_source(args.caller), args.callee.stem,
                                        read_source(args.callee), args.line)
    except (OSError, ValueError):
        pass
    if result:
        result.update(callerFile=args.caller.name, calleeFile=args.callee.name)
    print(json.dumps(result))
