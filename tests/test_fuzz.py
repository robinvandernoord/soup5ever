"""Differential fuzzing against html5lib, triaged with Chromium.

Opt-in, because it is slow and needs Node.js/Playwright/Chromium:

    pytest tests/test_fuzz.py --fuzz 20000 --fuzz-seed 7

Mismatches between soup5ever and html5lib are minimized and saved under
tests/fuzz_failures/; the test fails only for mismatches where Chromium
doesn't side with soup5ever. Turn real findings into cases in
tests/corpus.py.
"""

from __future__ import annotations

import pytest

from . import fuzz, html5lib_dat
from .oracle import classify


@pytest.fixture(scope="module")
def oracle(request):
    if not request.config.getoption("--fuzz"):
        pytest.skip("pass --fuzz N to run")
    if not classify.available():
        pytest.skip("Chromium oracle not available (see tests/oracle/classify.py)")


def test_chromium_matches_spec(oracle):
    """Calibrate the oracle on the html5lib-tests corpus."""
    cases = [c for c in html5lib_dat.all_cases() if c.applicable]
    if not cases:
        pytest.skip("html5lib-tests not downloaded")
    results = classify.chromium([c.data for c in cases])
    wrong = [c.id for c, r in zip(cases, results, strict=True) if r != c.document]
    assert len(wrong) <= 5, wrong


def test_fuzz(request, oracle):
    iterations = request.config.getoption("--fuzz")
    seed = request.config.getoption("--fuzz-seed")
    failures = fuzz.run(seed, iterations)
    distinct: dict[str, int] = {}
    for i, small, _ in failures:
        distinct.setdefault(small, i)
    verdicts = fuzz.triage(list(distinct)) if distinct else []
    bugs = [
        f"seed={seed} iteration={i}: {small!r} ({verdict})"
        for (small, i), verdict in zip(distinct.items(), verdicts, strict=True)
        if verdict != "html5lib bug"
    ]
    assert not bugs, "\n".join(bugs)
