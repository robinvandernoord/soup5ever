"""Triage differential mismatches with Chromium as an independent oracle.

    python -m tests.oracle.classify tests/fuzz_failures/*.html
    python -m tests.oracle.classify --calibrate     # vs html5lib-tests

For each input, prints whether soup5ever, html5lib (adapter bug fixed) and
Chromium's DOMParser agree. Needs Node.js with Playwright and a Chromium
(set NODE, NODE_PATH, CHROMIUM_PATH as needed). Not used by the test suite.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

from bs4 import BeautifulSoup

import soup5ever  # noqa: F401

from .. import canon, html5lib_dat

SCRIPT = Path(__file__).with_name("chromium.cjs")


def chromium(docs: list[str]) -> list[str]:
    env = dict(os.environ)
    env.setdefault("NODE_PATH", "/opt/node22/lib/node_modules")
    env.setdefault("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    node = env.get("NODE", "/opt/node22/bin/node")
    out = subprocess.run(
        [node, str(SCRIPT)],
        input=json.dumps(docs),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return json.loads(out.stdout)


def trees(markup: str) -> tuple[str, str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ours = BeautifulSoup(markup, "html5ever", multi_valued_attributes=None)
        with canon.html5lib_adapter_fixed():
            theirs = BeautifulSoup(markup, "html5lib", multi_valued_attributes=None)
    return canon.to_test_format(ours), canon.to_test_format(theirs)


def calibrate() -> None:
    cases = [c for c in html5lib_dat.all_cases() if c.applicable]
    results = chromium([c.data for c in cases])
    bad = [c.id for c, r in zip(cases, results, strict=True) if r != c.document]
    print(f"Chromium matches the spec corpus on {len(cases) - len(bad)}/{len(cases)} cases")
    print("mismatches:", " ".join(bad))


def main(paths: list[str]) -> None:
    docs = [Path(p).read_text(encoding="utf-8") for p in paths]
    for path, markup, browser in zip(paths, docs, chromium(docs), strict=True):
        ours, theirs = trees(markup)
        verdict = (
            "html5lib wrong (soup5ever == chromium)"
            if ours == browser != theirs
            else "SOUP5EVER WRONG (html5lib == chromium)"
            if theirs == browser != ours
            else "agree"
            if ours == theirs
            else "all three differ"
        )
        print(f"{verdict:42s} {markup!r:.70}  [{path}]")


if __name__ == "__main__":
    if sys.argv[1:] == ["--calibrate"]:
        calibrate()
    else:
        main(sys.argv[1:])
