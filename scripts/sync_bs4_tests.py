"""Vendor BeautifulSoup's tree-builder test infrastructure into tests/vendor.

soup5ever runs BeautifulSoup's own ``HTML5TreeBuilderSmokeTest`` (and the
tests of BS4's html5lib builder) against the html5ever builder. Those tests
live in ``bs4/tests``, which is only shipped in the BeautifulSoup sdist, so
this script downloads the sdist and copies the relevant files.

    python scripts/sync_bs4_tests.py            # version of the installed bs4
    python scripts/sync_bs4_tests.py 4.15.0     # a specific version

CI runs this before the test suite so the smoke tests always match the bs4
version under test.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tarfile
import tempfile

FILES = ["__init__.py", "test_html5lib.py"]
DEST = pathlib.Path(__file__).resolve().parent.parent / "tests" / "vendor" / "bs4_tests"


def main() -> None:
    if len(sys.argv) > 1:
        version = sys.argv[1]
    else:
        import bs4

        version = bs4.__version__
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [
                sys.executable, "-m", "pip", "download", "--quiet", "--no-deps",
                "--no-binary", ":all:", f"beautifulsoup4=={version}", "-d", tmp,
            ],
            check=True,
        )
        [sdist] = pathlib.Path(tmp).glob("beautifulsoup4-*.tar.gz")
        with tarfile.open(sdist) as tar:
            DEST.mkdir(parents=True, exist_ok=True)
            for name in FILES:
                member = tar.getmember(f"beautifulsoup4-{version}/bs4/tests/{name}")
                data = tar.extractfile(member).read()
                (DEST / name).write_bytes(data)
    (DEST / "VERSION").write_text(version + "\n")
    print(f"vendored bs4 {version} tests into {DEST}")


if __name__ == "__main__":
    main()
