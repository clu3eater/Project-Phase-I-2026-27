#!/usr/bin/env bash
# Start the aero piston engine digital twin. DRDO / IDEX PS 26054.
#
# A thin wrapper around run.py, which does the real work. This exists only to
# pick an interpreter: `python` is Python 2 or absent on some systems, and the
# launcher has to run before the project's virtual environment exists.
#
#   ./run.sh              install what is missing, self-check, serve
#   ./run.sh --check      every check, no server
#   ./run.sh --demo       the 90-second terminal demonstration

set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usable() {
    [ -x "$1" ] || command -v "$1" >/dev/null 2>&1 || return 1
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null
}

py=""
if [ -x "$root/.venv/bin/python" ]; then
    py="$root/.venv/bin/python"
else
    for c in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$c" >/dev/null 2>&1 && usable "$c"; then
            py="$(command -v "$c")"
            break
        fi
    done
fi

if [ -z "$py" ]; then
    echo
    echo "No usable Python 3.11+ was found on PATH."
    echo "Install Python 3.11 or newer and run this again."
    echo
    exit 1
fi

exec "$py" "$root/run.py" "$@"
