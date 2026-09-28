import pathlib
import sys

# Make `benchmarks.documents` importable from the tests.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# BS4's vendored tests are run through tests/test_bs4_smoke.py, not directly.
collect_ignore = ["vendor"]
