def run(value):
    scope = {'__builtins__': {}}
    local_scope = {}
    exec(value, scope, local_scope)
    return local_scope.get("answer")
