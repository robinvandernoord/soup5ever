"""The html5lib-tests tree-construction corpus.

Two checks per applicable case (whole documents, scripting disabled; BS4
has no fragment parsing):

* spec: soup5ever's BeautifulSoup tree, serialized in the corpus' own
  format, equals the expected tree. This exercises exactly the boundary this
  project adds: html5ever's semantics surviving Rust -> Python conversion
  into BS4 objects (namespaces, NamespacedAttributes, doctypes, template
  contents, text merging).
* differential: soup5ever vs BeautifulSoup(markup, "html5lib"). Every
  disagreement must be explained: either soup5ever matches the spec and
  html5lib does not (html5lib-python 1.1 predates many spec changes, and
  BS4's adapter has a few bugs of its own), or the case is listed in
  `SPEC_FAILURES`.

Run `python scripts/fetch_html5lib_tests.py` to download the corpus; the
tests are skipped without it.
"""

from __future__ import annotations

import warnings

import pytest
from bs4 import BeautifulSoup

import soup5ever  # noqa: F401

from . import canon, html5lib_dat, html5lib_native

CASES = [case for case in html5lib_dat.all_cases() if case.applicable]

pytestmark = pytest.mark.skipif(
    not CASES, reason="html5lib-tests not downloaded (scripts/fetch_html5lib_tests.py)"
)

#: Cases where soup5ever's tree doesn't match the spec expectation.
SPEC_FAILURES = {
    # html5ever only runs "maybe clone an option into selectedcontent" on an
    # explicit </option> (servo/html5ever#712), and soup5ever doesn't
    # implement the clone at all: BeautifulSoup has no live DOM, and html5lib
    # doesn't do it either.
    "webkit02:44": "selectedcontent cloning not implemented",
    "webkit02:45": "selectedcontent cloning not implemented",
    "webkit02:46": "selectedcontent cloning not implemented",
    "webkit02:47": "selectedcontent cloning not implemented",
}


def parse(markup, parser):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return BeautifulSoup(markup, parser, multi_valued_attributes=None)


def ids(case):
    return case.id


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_spec(case):
    ours = parse(case.data, "html5ever")
    assert canon.linkage_problems(ours) == []
    actual = canon.to_test_format(ours)
    if case.id in SPEC_FAILURES:
        assert actual != case.document, f"{case.id} now passes; remove it from SPEC_FAILURES"
        pytest.xfail(SPEC_FAILURES[case.id])
    assert actual == case.document


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_differential(case):
    ours = parse(case.data, "html5ever")
    theirs = parse(case.data, "html5lib")
    if canon.canonical(ours) == canon.canonical(theirs):
        return
    if case.id in SPEC_FAILURES:
        pytest.xfail(SPEC_FAILURES[case.id])
    # The difference is acceptable only because html5lib is the one that's
    # wrong.
    assert canon.to_test_format(ours) == case.document
    assert canon.to_test_format(theirs) != case.document


def classify():
    """Summary used for the README: counts per category."""
    counts = {
        "identical": 0,
        "html5lib parser differs from spec": 0,
        "BS4 html5lib adapter differs from html5lib": 0,
        "soup5ever differs from spec": 0,
    }
    for case in CASES:
        ours = parse(case.data, "html5ever")
        theirs = parse(case.data, "html5lib")
        if canon.canonical(ours) == canon.canonical(theirs):
            counts["identical"] += 1
        elif canon.to_test_format(ours) != case.document:
            counts["soup5ever differs from spec"] += 1
        elif html5lib_native.to_test_format(case.data) == case.document:
            counts["BS4 html5lib adapter differs from html5lib"] += 1
        else:
            counts["html5lib parser differs from spec"] += 1
    return counts


if __name__ == "__main__":  # python -m tests.test_html5lib_tests
    print(len(CASES), "applicable cases")
    for name, count in classify().items():
        print(f"{count:5d}  {name}")
