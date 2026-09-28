"""Download the upstream html5lib-tests corpus into tests/data/html5lib-tests.

The tree-construction tests are used two ways: as a corpus of adversarial
HTML for the html5lib-vs-html5ever differential tests, and as a spec-level
check that html5ever's tree survives conversion into BeautifulSoup objects.
Tests that need the corpus are skipped when it is absent.

    python scripts/fetch_html5lib_tests.py
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

#: The last commit before the tree-construction tests moved to
#: web-platform-tests (html/syntax/parsing) in June 2026. Pinned so results
#: are reproducible.
COMMIT = "9329e64694e7835d0dcff9811e22856ef6ad16f9"
REPO = "https://github.com/html5lib/html5lib-tests.git"
DEST = pathlib.Path(__file__).resolve().parent.parent / "tests" / "data" / "html5lib-tests"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:

        def git(*args: str) -> None:
            subprocess.run(["git", "-C", tmp, *args], check=True, capture_output=True)

        git("init", "-q")
        git("remote", "add", "origin", REPO)
        git("fetch", "-q", "--depth", "1", "origin", COMMIT)
        git("checkout", "-q", "FETCH_HEAD")
        if DEST.exists():
            shutil.rmtree(DEST)
        DEST.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pathlib.Path(tmp) / "tree-construction", DEST / "tree-construction")
    (DEST / "COMMIT").write_text(COMMIT + "\n")
    print(f"html5lib-tests {COMMIT[:12]} -> {DEST}")


if __name__ == "__main__":
    main()
