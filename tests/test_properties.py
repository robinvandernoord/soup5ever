"""Property tests on soup5ever's own output (no reference parser needed).

Inputs come from the fuzzer's HTML token grammar (tests/fuzz.py), driven by
Hypothesis. `derandomize=True` keeps runs reproducible and fast enough for
the ordinary test suite; the heavier differential fuzzing is opt-in.
"""

from __future__ import annotations

import random

import pytest
from bs4 import BeautifulSoup
from hypothesis import given, settings
from hypothesis import strategies as st

import soup5ever  # noqa: F401

from . import canon
from .fuzz import SEEDS, generate, mutate

markup = st.one_of(
    st.randoms(use_true_random=False).map(generate),
    st.tuples(st.randoms(use_true_random=False), st.sampled_from(SEEDS)).map(lambda args: mutate(args[0], args[1])),
    st.text(alphabet=st.sampled_from(list("<>/=&;#x0a!-\"' \n\r\x00pbtdsvgm")), max_size=60),
)

pytestmark = pytest.mark.filterwarnings("ignore")

SETTINGS = settings(max_examples=300, derandomize=True, deadline=None, database=None)


@SETTINGS
@given(markup)
def test_linkage_is_consistent(doc):
    assert canon.linkage_problems(BeautifulSoup(doc, "html5ever")) == []


@SETTINGS
@given(markup)
def test_position_tracking_does_not_change_the_tree(doc):
    # With positions on, the tokenizer is fed in many small chunks; with them
    # off, in one. The tree must not depend on chunking.
    with_positions = BeautifulSoup(doc, "html5ever")
    without = BeautifulSoup(doc, "html5ever", store_line_numbers=False)
    assert canon.canonical(with_positions) == canon.canonical(without)


@SETTINGS
@given(markup)
def test_positions_are_plausible(doc):
    lines = doc.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for tag in BeautifulSoup(doc, "html5ever").find_all(True):
        if tag.sourceline is None:
            continue
        assert 1 <= tag.sourceline <= len(lines)
        assert -1 <= tag.sourcepos <= len(lines[tag.sourceline - 1])


@SETTINGS
@given(markup)
def test_bytes_and_str_agree(doc):
    if doc.startswith("﻿"):
        return
    from_str = BeautifulSoup(doc, "html5ever")
    from_bytes = BeautifulSoup(doc.encode("utf-8"), "html5ever", from_encoding="utf-8")
    assert canon.canonical(from_bytes) == canon.canonical(from_str)


@SETTINGS
@given(st.binary(max_size=200))
def test_arbitrary_bytes_parse(data):
    doc = BeautifulSoup(data, "html5ever")
    assert doc.original_encoding
    assert canon.linkage_problems(doc) == []


def test_generator_is_deterministic():
    assert generate(random.Random(5)) == generate(random.Random(5))
