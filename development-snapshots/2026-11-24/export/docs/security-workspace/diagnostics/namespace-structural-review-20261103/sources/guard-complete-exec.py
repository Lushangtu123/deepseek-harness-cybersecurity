def run(value, other=None, enforce=True):
    if value not in ('answer=6*7', 'answer=7*8'):
        raise ValueError("outside fixed set")
    scope = {'__builtins__': {}}
    exec(value, scope)
    return scope.get("answer")
