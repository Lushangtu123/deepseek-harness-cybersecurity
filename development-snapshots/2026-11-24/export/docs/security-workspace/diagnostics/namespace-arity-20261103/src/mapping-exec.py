def run(value, other=None, enforce=True):
    value = {"allowed": 'answer=6*7'}.get(value, 'answer=7*8')
    scope = {'__builtins__': {}}
    exec(value, scope)
    return scope.get("answer")
