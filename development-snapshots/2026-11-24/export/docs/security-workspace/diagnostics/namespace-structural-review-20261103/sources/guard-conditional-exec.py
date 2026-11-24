def run(value, other=None, enforce=True):
    if enforce and value not in ('answer=6*7', 'answer=7*8'):
        raise ValueError("conditional check")
    scope = {'__builtins__': {}}
    exec(value, scope)
    return scope.get("answer")
