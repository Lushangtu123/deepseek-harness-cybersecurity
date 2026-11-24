import builtins
def run(value):
    scope = {'__builtins__': {}}
    return builtins.eval(value, scope)
