"""Synthetic experiment fixture: quoting sink.

The frozen input is interpolated into a double-quoted string literal before
the dynamic call.  The input is therefore data, never program structure.
Development diagnostic only; never import or execute outside the reviewed
pinned container protocol.
"""
import sys

OPTION = "--expr="


def render(source):
    return eval('str("' + source + '")')


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
    try:
        render(value)
    except SyntaxError:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
