from builtins import eval as evaluate
def run(value):
    scope = {'__builtins__': {}}
    return evaluate(value, scope)
