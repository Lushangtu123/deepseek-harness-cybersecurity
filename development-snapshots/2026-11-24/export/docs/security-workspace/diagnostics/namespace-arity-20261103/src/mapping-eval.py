def run(value, other=None, enforce=True):
    value = {"allowed": '6*7'}.get(value, '7*8')
    scope = {'__builtins__': {}}
    return eval(value, scope)
