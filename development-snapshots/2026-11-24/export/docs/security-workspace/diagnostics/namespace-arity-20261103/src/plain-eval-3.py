def run(value):
    scope = {'__builtins__': {}}
    local_scope = {}
    return eval(value, scope, local_scope)
