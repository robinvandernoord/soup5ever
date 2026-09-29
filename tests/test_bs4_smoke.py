"""BeautifulSoup's own tree-builder contract, run against soup5ever.

BS4's `TestHTML5LibBuilder` is `HTML5TreeBuilderSmokeTest` (the suite
every HTML5 tree builder is expected to pass, itself built on
`HTMLTreeBuilderSmokeTest`) plus the html5lib builder's own tests, many of
which exercise html5lib's tree fix-ups: reparenting, foster parenting,
cloning. It also carries html5lib's documented opt-outs (`parse_only`,
string container classes), which soup5ever shares. Running that class with
soup5ever as the builder checks soup5ever against exactly the contract
html5lib is held to. The tests are vendored from the BeautifulSoup sdist by
`scripts/fetch_upstream_tests.py`.

The only overrides are tests whose expected strings name the html5lib
builder itself.
"""

import warnings

import pytest
from bs4 import BeautifulSoup
from bs4.filter import SoupStrainer

from soup5ever import HTML5everTreeBuilder

from .vendor.bs4_tests import test_html5lib as upstream


class TestAsHTML5Lib(upstream.TestHTML5LibBuilder):
    """BS4's html5lib-builder tests, with soup5ever as the builder."""

    @property
    def default_builder(self):
        return HTML5everTreeBuilder

    def test_soupstrainer(self):
        strainer = SoupStrainer("b")
        markup = "<p>A <b>bold</b> statement.</p>"
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            soup = BeautifulSoup(markup, "html5ever", parse_only=strainer)
        assert soup.decode() == self.document_for(markup)
        [warning] = w
        assert warning.filename == __file__
        assert "the html5ever tree builder doesn't support parse_only" in str(warning.message)

    @pytest.mark.parametrize(
        "name,value",
        [("document_declared_encoding", "utf8"), ("exclude_encodings", ["utf8"])],
    )
    def test_prepare_markup_warnings(self, name, value):
        builder = self.default_builder()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            list(builder.prepare_markup("a", **{name: value}))
        [warning] = w
        assert str(warning.message) == (
            f"You provided a value for {name}, but the html5ever tree builder doesn't support {name}."
        )
