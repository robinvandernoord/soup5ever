import pathlib
import sys

# Make `benchmarks.documents` importable from the tests.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# BS4's vendored tests are run through tests/test_bs4_smoke.py, not directly.
collect_ignore = ["vendor"]


def pytest_addoption(parser):
    group = parser.getgroup("soup5ever")
    group.addoption(
        "--fuzz",
        type=int,
        default=3000,
        metavar="N",
        help="generated inputs for tests/test_fuzz.py (default 3000)",
    )
    group.addoption("--fuzz-seed", type=int, default=1, help="seed for tests/test_fuzz.py")
