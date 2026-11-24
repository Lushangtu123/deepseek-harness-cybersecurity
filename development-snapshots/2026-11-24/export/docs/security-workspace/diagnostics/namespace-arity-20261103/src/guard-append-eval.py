def run(value, other=None, enforce=True):
    if value not in ('6*7', '7*8'):
        raise ValueError("outside fixed set")
    value += other
    scope = {'__builtins__': {}}
    return eval(value, scope)
