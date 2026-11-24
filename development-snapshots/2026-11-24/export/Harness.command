#!/bin/sh
set -eu
launcher_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
exec /opt/homebrew/bin/python3 "$launcher_dir/scripts/harness_launcher.py"
