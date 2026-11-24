def run(value):
    scope = {'__builtins__': {}}
    local_scope = {}
    exec(value, scope)
    return scope.get("answer")
