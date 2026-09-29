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
        default=0,
        metavar="N",
        help="run differential fuzzing with N generated inputs (tests/test_fuzz.py)",
    )
    group.addoption("--fuzz-seed", type=int, default=1, help="seed for --fuzz")
