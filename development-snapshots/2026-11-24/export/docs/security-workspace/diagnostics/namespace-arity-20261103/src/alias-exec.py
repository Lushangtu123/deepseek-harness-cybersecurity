from builtins import exec as evaluate
def run(value):
    scope = {'__builtins__': {}}
    evaluate(value, scope)
    return scope.get("answer")
