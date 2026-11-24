def run(value):
    scope = {'__builtins__': {}}
    local_scope = {}
    exec(value)
    return locals().get("answer")
