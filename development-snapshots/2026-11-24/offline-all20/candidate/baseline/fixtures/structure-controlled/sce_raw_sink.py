"""Synthetic experiment fixture: raw dynamic-evaluation sink.

Development diagnostic only.  Never import or execute this module outside the
reviewed pinned container protocol.  The single eval call below is the bound
experiment point; the input value is produced by the fixture's own argv parser
from the task-frozen ``--expr=`` option.
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
    compute(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
