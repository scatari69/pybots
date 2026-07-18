#!/usr/bin/env python3
"""Stand-in for the real simc binary, used by test_simc_runner.py.

Mimics just enough of simc's behavior for the runner to exercise: reads the
input profile file (first positional arg), writes an html report if asked to,
and fails if the profile contains the literal string "FAIL".
"""
import sys
from pathlib import Path

args = sys.argv[1:]
input_path = Path(args[0])
content = input_path.read_text()

if "FAIL" in content:
    print("boom", file=sys.stderr)
    sys.exit(1)

for arg in args[1:]:
    if arg.startswith("html="):
        Path(arg.split("=", 1)[1]).write_text("<html>report</html>")

sys.exit(0)
