def exec(value, namespace):
    return value
def run(value):
    return exec(value, {})
