"""Synthetic experiment fixture: two identical call sites in two functions.

``alpha`` and ``beta`` have byte-identical bodies, so their dynamic CALL
instructions share the same code-unit offset.  The task binds the eval call in
``alpha`` only; an input routed to ``beta`` produces a real dynamic event at
the same offset and must be rejected by caller identity, never borrowed.
Development diagnostic only; never import or execute outside the reviewed
protocol.
"""
import sys


def alpha(value):
    return eval(value)


def beta(value):
    return eval(value)


def parse(argv):
    route = None
    value = None
    for item in argv:
        if item.startswith("--route="):
            route = item[len("--route="):]
        elif item.startswith("--expr="):
            value = item[len("--expr="):]
        else:
            return None, None
    return route, value


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    route, value = parse(argv)
    if route is None or value is None:
        return 2
    if route == "alpha":
        alpha(value)
    elif route == "beta":
        beta(value)
    else:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
