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

Run `python scripts/fetch_upstream_tests.py` to download the corpus; the
tests are skipped without it.
"""

from __future__ import annotations

import warnings

import pytest
from bs4 import BeautifulSoup

import soup5ever  # noqa: F401

from . import canon, html5lib_dat

CASES = [case for case in html5lib_dat.all_cases() if case.applicable]

pytestmark = pytest.mark.skipif(
    not CASES, reason="html5lib-tests not downloaded (scripts/fetch_upstream_tests.py)"
)

# Cases where soup5ever's tree doesn't match the spec expectation.
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


PASSING = [case for case in CASES if case.id not in SPEC_FAILURES]


@pytest.mark.parametrize("case", PASSING, ids=ids)
def test_spec(case):
    ours = parse(case.data, "html5ever")
    assert canon.linkage_problems(ours) == []
    assert canon.to_test_format(ours) == case.document


@pytest.mark.parametrize("case", PASSING, ids=ids)
def test_differential(case):
    ours = parse(case.data, "html5ever")
    theirs = parse(case.data, "html5lib")
    if canon.canonical(ours) == canon.canonical(theirs):
        return
    # The difference is acceptable only because html5lib is the one that's
    # wrong.
    assert canon.to_test_format(ours) == case.document
    assert canon.to_test_format(theirs) != case.document


def test_known_spec_failures():
    """The listed failures still fail; remove any that start passing."""
    failures = {case.id: case for case in CASES if case.id in SPEC_FAILURES}
    assert failures.keys() == SPEC_FAILURES.keys()
    for case in failures.values():
        ours = parse(case.data, "html5ever")
        assert canon.to_test_format(ours) != case.document, f"{case.id} now passes"
