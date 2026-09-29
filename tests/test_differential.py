"""Differential tests: BeautifulSoup(markup, "html5ever") vs "html5lib".

The comparison is on `canon.canonical` trees (node types, names,
namespaces, prefixes, attributes including NamespacedAttribute details and
list-valued attributes, text, child order), not on serialized HTML.
Navigation pointers are checked separately, because html5lib's adapter is
known to get some of them wrong (see test_html5lib_linkage_quirk).
"""

from __future__ import annotations

import warnings

import pytest
from bs4 import BeautifulSoup

import soup5ever  # noqa: F401  (registers the builder)
from benchmarks.documents import TEST_DOCUMENTS

from . import canon
from .corpus import CASES, KNOWN_DIFFERENCES


def parse(markup, parser, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return BeautifulSoup(markup, parser, **kwargs)


def compare(markup, fixed_adapter=False, **kwargs):
    ours = parse(markup, "html5ever", **kwargs)
    if fixed_adapter:
        with canon.html5lib_adapter_fixed():
            theirs = parse(markup, "html5lib", **kwargs)
    else:
        theirs = parse(markup, "html5lib", **kwargs)
    assert canon.linkage_problems(ours) == []
    return canon.diff(canon.canonical(ours), canon.canonical(theirs)), ours, theirs


@pytest.mark.parametrize("case", sorted(CASES))
def test_corpus_case(case):
    difference, _, _ = compare(CASES[case])
    if case in KNOWN_DIFFERENCES:
        assert difference, f"{case} is listed as a known difference but now matches html5lib"
    else:
        assert difference is None


def test_adapter_fix_explains_bs4_adapter_differences():
    for case, (kind, _) in KNOWN_DIFFERENCES.items():
        difference, _, _ = compare(CASES[case], fixed_adapter=True)
        assert (difference is None) == (kind == "bs4-adapter"), case


# A leading U+FEFF is content in a str but a byte order mark in bytes.
BYTES_CASES = sorted(k for k, v in CASES.items() if not v.startswith("\ufeff"))
# Cases where both builders produce the same tree.
SAME_TREE_CASES = sorted(k for k in CASES if k not in KNOWN_DIFFERENCES)


@pytest.mark.parametrize("case", BYTES_CASES)
def test_corpus_case_as_utf8_bytes(case):
    # Same tree from bytes as from str (for documents that are valid UTF-8,
    # soup5ever detects UTF-8; html5lib would guess windows-1252 without
    # chardet, so the comparison here is soup5ever-with-itself).
    markup = CASES[case]
    from_str = parse(markup, "html5ever")
    from_bytes = parse(markup.encode("utf-8"), "html5ever", from_encoding="utf-8")
    assert canon.canonical(from_bytes) == canon.canonical(from_str)


@pytest.mark.parametrize("case", sorted(CASES))
def test_corpus_case_without_multivalued_attributes(case):
    difference, _, _ = compare(CASES[case], multi_valued_attributes=None)
    assert (difference is None) == (case not in KNOWN_DIFFERENCES)


@pytest.mark.parametrize("kind", sorted(TEST_DOCUMENTS))
def test_generated_documents(kind):
    """Larger, realistic documents (the benchmark generators, scaled down)."""
    markup = TEST_DOCUMENTS[kind]()
    # Random tag soup trips BS4's html5lib-adapter Noah's Ark bug, so the
    # reference here is html5lib with that bug fixed.
    difference, ours, theirs = compare(markup, fixed_adapter=True)
    assert difference is None
    # Declared as utf-8 in the document, so html5lib agrees on bytes too.
    difference, ours, theirs = compare(markup.encode("utf-8"), fixed_adapter=True)
    if "charset=utf-8" in markup:
        assert difference is None
        assert ours.original_encoding == theirs.original_encoding == "utf-8"


def test_soup_linkage_matches_html5lib():
    # html5lib's adapter links the soup and the first node, unless that node
    # is a doctype; soup5ever follows suit.
    for markup in ["<p>x", "<!--c--><p>x", "<!DOCTYPE html><p>x", ""]:
        ours, theirs = parse(markup, "html5ever"), parse(markup, "html5lib")
        assert (ours.next_element is ours.contents[0]) == (theirs.next_element is theirs.contents[0])
        assert canon.linkage_problems(ours) == []


@pytest.mark.parametrize("case", SAME_TREE_CASES)
def test_navigation_matches_html5lib(case):
    """next_element/previous_element chains, compared node by node."""
    difference, ours, theirs = compare(CASES[case])
    assert difference is None
    assert canon.linkage_problems(theirs) == []

    def chain(soup):
        out, node = [], soup
        while node is not None:
            out.append(canon.canonical(node) if node is not soup else "#soup")
            node = node.next_element
        return out

    assert chain(ours) == chain(theirs)
