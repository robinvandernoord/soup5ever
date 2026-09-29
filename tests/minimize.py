"""Delta-debugging minimizer for differential mismatches.

Shrinks the input while BeautifulSoup(markup, "html5ever") and
BeautifulSoup(markup, "html5lib") still produce different canonical trees.
"""

from __future__ import annotations

import warnings

from bs4 import BeautifulSoup

import soup5ever  # noqa: F401

from . import canon


def differs(markup: str) -> bool:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ours = BeautifulSoup(markup, "html5ever")
        theirs = BeautifulSoup(markup, "html5lib")
    return canon.canonical(ours) != canon.canonical(theirs)


def minimize(markup: str, predicate=differs) -> str:
    """ddmin over characters, starting with large chunks."""
    assert predicate(markup)
    n = 2
    while len(markup) >= 2:
        chunk = max(1, len(markup) // n)
        reduced = False
        for start in range(0, len(markup), chunk):
            candidate = markup[:start] + markup[start + chunk :]
            if candidate and predicate(candidate):
                markup = candidate
                n = max(n - 1, 2)
                reduced = True
                break
        if not reduced:
            if chunk == 1:
                break
            n = min(n * 2, len(markup))
    return markup
