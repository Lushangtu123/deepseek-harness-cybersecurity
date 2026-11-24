def run(value, other=None, enforce=True):
    scope = {'__builtins__': {}}
    return eval('6*7', scope)
