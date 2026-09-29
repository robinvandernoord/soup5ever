"""Fetch the upstream test suites soup5ever runs against.

    python scripts/fetch_upstream_tests.py            # tests for the installed bs4
    python scripts/fetch_upstream_tests.py --bs4 4.14.3

* BeautifulSoup's tree-builder tests (`bs4/tests/__init__.py` and
  `test_html5lib.py`, only shipped in the sdist) go into tests/vendor/bs4_tests,
  for tests/test_bs4_smoke.py. These are committed; re-run after changing the
  bs4 version.
* The html5lib-tests tree-construction corpus goes into
  tests/data/html5lib-tests (gitignored), for tests/test_html5lib_tests.py.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BS4_DEST = ROOT / "tests" / "vendor" / "bs4_tests"
BS4_FILES = ["__init__.py", "test_html5lib.py"]
HTML5LIB_TESTS_DEST = ROOT / "tests" / "data" / "html5lib-tests"
HTML5LIB_TESTS_REPO = "https://github.com/html5lib/html5lib-tests.git"
# The last commit before the tree-construction tests moved to
# web-platform-tests (html/syntax/parsing) in June 2026.
HTML5LIB_TESTS_COMMIT = "9329e64694e7835d0dcff9811e22856ef6ad16f9"


def fetch_bs4_tests(version: str, dest: pathlib.Path = BS4_DEST) -> None:
    with urllib.request.urlopen(f"https://pypi.org/pypi/beautifulsoup4/{version}/json") as r:
        [sdist] = [u for u in json.load(r)["urls"] if u["packagetype"] == "sdist"]
    with urllib.request.urlopen(sdist["url"]) as r:
        data = r.read()
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for name in BS4_FILES:
            member = tar.getmember(f"beautifulsoup4-{version}/bs4/tests/{name}")
            (dest / name).write_bytes(tar.extractfile(member).read())
    (dest / "VERSION").write_text(version + "\n")
    print(f"bs4 {version} tests -> {dest}")


def fetch_html5lib_tests(dest: pathlib.Path = HTML5LIB_TESTS_DEST) -> None:
    with tempfile.TemporaryDirectory() as tmp:

        def git(*args: str) -> None:
            # autocrlf would rewrite the literal CRs some test cases contain.
            cmd = ["git", "-c", "core.autocrlf=false", "-C", tmp, *args]
            subprocess.run(cmd, check=True, capture_output=True)

        git("init", "-q")
        git("remote", "add", "origin", HTML5LIB_TESTS_REPO)
        git("fetch", "-q", "--depth", "1", "origin", HTML5LIB_TESTS_COMMIT)
        git("checkout", "-q", "FETCH_HEAD")
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pathlib.Path(tmp) / "tree-construction", dest / "tree-construction")
    (dest / "COMMIT").write_text(HTML5LIB_TESTS_COMMIT + "\n")
    print(f"html5lib-tests {HTML5LIB_TESTS_COMMIT[:12]} -> {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the upstream test suites.")
    parser.add_argument("--bs4", metavar="VERSION", help="default: the installed version")
    args = parser.parse_args()
    if args.bs4 is None:
        import bs4

        args.bs4 = bs4.__version__
    fetch_bs4_tests(args.bs4)
    fetch_html5lib_tests()


if __name__ == "__main__":
    main()
