import builtins
def run(value):
    scope = {'__builtins__': {}}
    builtins.exec(value, scope)
    return scope.get("answer")
