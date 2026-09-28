import pathlib
import sys

# Make `benchmarks.documents` importable from the tests.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
