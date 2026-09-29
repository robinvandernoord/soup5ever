"""Chromium's DOMParser as an independent oracle for triaging mismatches.

Used by tests/test_fuzz.py. Needs Node.js with Playwright and a Chromium
(set NODE, NODE_PATH, CHROMIUM_PATH as needed).
"""

from __future__ import annotations

import json
import os
import subprocess
import warnings
from pathlib import Path

from bs4 import BeautifulSoup

import soup5ever  # noqa: F401

from .. import canon

SCRIPT = Path(__file__).with_name("chromium.cjs")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("NODE_PATH", "/opt/node22/lib/node_modules")
    env.setdefault("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
    return env


def available() -> bool:
    try:
        return chromium(["<p>x"]) != []
    except (OSError, subprocess.CalledProcessError, ValueError):
        return False


def chromium(docs: list[str]) -> list[str]:
    """Each document parsed by Chromium, in html5lib-tests format."""
    env = _env()
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
