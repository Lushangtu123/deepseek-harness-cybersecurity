"""Synthetic experiment fixture: stdout echo with a dormant sink.

``compute`` contains the same kind of dynamic call as the raw-sink fixture, but
``main`` never calls it.  All observable output is ordinary target stdout and
must never be treated as execution evidence.  Development diagnostic only.
"""
import sys

OPTION = "--expr="


def compute(source):
    return eval(source)


def parse(argv):
    value = None
    for item in argv:
        if item.startswith(OPTION):
            value = item[len(OPTION):]
        else:
            return None
    return value


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    value = parse(argv)
    if value is None:
        return 2
    text = "challenge=" + value + "\n"
    sys.stdout.write(text)
    sys.stdout.write("EVAL run=echo tag=stdout off=0 value=" + value + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
