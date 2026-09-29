"""Differential fuzzing against html5lib.

Part of the normal `pytest` run: 3000 generated inputs from a fixed seed.
Every mismatch between soup5ever and html5lib is minimized and must be one
of the `KNOWN` html5lib bugs below (each confirmed with Chromium's parser).
With a fixed seed that set is deterministic, so no browser is needed.

A mismatch outside the set fails the test and is saved under
tests/fuzz_failures/. When Chromium is available (tests/oracle), new
mismatches are triaged automatically and only those Chromium doesn't blame
on html5lib fail. Bigger runs: `pytest tests/test_fuzz.py --fuzz 20000
--fuzz-seed 7`.
"""

from __future__ import annotations

from . import fuzz
from .oracle import classify

# Minimized mismatches for the default seed and iterations; html5lib is wrong
# in every one (Chromium agrees with soup5ever).
KNOWN = {
    "<a><summary><a>",
    "<b l><b><b><b><b></b></b></b></b>>",
    "<big><summary></big>",
    "<em><summary></em>",
    "<font><s></font><template>",
    "<listing></a>\n",
    "<listing><tfoot>\n",
    "<math></br>",
    "<math></p>",
    "<nobr><main><nobr>",
    "<strike><main></strike>",
    "<svg></br>",
    "<svg></p>",
    "<svg><title><b></title><",
    "<table><s><table><textarea>h",
    "<table><strong><col><textarea><",
    "<table><template>",
    "<table><textarea>\r",
    "<template>",
    "<u><template></u><",
}


def test_fuzz(request):
    seed = request.config.getoption("--fuzz-seed")
    iterations = request.config.getoption("--fuzz")
    found = {small: i for i, small, _ in reversed(fuzz.run(seed, iterations, save=False))}
    new = sorted(set(found) - KNOWN)
    if new and classify.available():
        new = [
            m for m, verdict in zip(new, fuzz.triage(new), strict=True) if verdict != "html5lib bug"
        ]
    for markup in new:
        fuzz.save_failure(markup)
    assert not new, "\n".join(f"seed={seed} iteration={found[m]}: {m!r}" for m in new)
