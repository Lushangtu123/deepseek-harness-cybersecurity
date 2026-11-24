def run(value, other=None, enforce=True):
    if enforce and value not in ('6*7', '7*8'):
        raise ValueError("conditional check")
    scope = {'__builtins__': {}}
    return eval(value, scope)
