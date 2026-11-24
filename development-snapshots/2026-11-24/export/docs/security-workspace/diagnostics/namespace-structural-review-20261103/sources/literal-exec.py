def run(value, other=None, enforce=True):
    scope = {'__builtins__': {}}
    exec('answer=6*7', scope)
    return scope.get("answer")
