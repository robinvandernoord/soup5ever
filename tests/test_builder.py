"""Behavior of the builder itself: registration, encodings, positions, and
regression tests for compatibility issues found during development."""

from __future__ import annotations

import copy
import pickle
import threading
import warnings

import pytest
from bs4 import BeautifulSoup
from bs4.builder import builder_registry
from bs4.element import (
    Comment,
    Doctype,
    NamespacedAttribute,
    NavigableString,
    Tag,
)

import soup5ever
from soup5ever import HTML5everTreeBuilder

from . import canon


def soup(markup, **kwargs):
    return BeautifulSoup(markup, "html5ever", **kwargs)


def html5lib(markup, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return BeautifulSoup(markup, "html5lib", **kwargs)


# --- registration ----------------------------------------------------------


def test_feature_names():
    assert builder_registry.lookup("html5ever") is HTML5everTreeBuilder
    assert builder_registry.lookup("soup5ever") is HTML5everTreeBuilder
    assert type(soup("<p>").builder) is HTML5everTreeBuilder
    assert BeautifulSoup("<p>", "soup5ever").builder.NAME == "html5ever"


def test_generic_features_keep_their_meaning():
    # Importing soup5ever must not change what the generic names select.
    from bs4.builder import HTML5TreeBuilder, HTMLParserTreeBuilder

    assert builder_registry.lookup("html5") is HTML5TreeBuilder
    assert builder_registry.lookup("html", "fast") is not HTML5everTreeBuilder
    assert builder_registry.lookup("html") is not HTML5everTreeBuilder
    assert builder_registry.lookup() is not HTML5everTreeBuilder
    assert type(BeautifulSoup("<p>", "html.parser").builder) is HTMLParserTreeBuilder
    # Combined with its own name, generic features still find it.
    assert builder_registry.lookup("html5ever", "html5") is HTML5everTreeBuilder
    assert builder_registry.lookup("html5ever", "permissive") is HTML5everTreeBuilder


def test_generic_features_fall_back_to_html5ever():
    from bs4.builder import TreeBuilderRegistry

    registry = TreeBuilderRegistry()
    soup5ever.register(registry)
    assert registry.lookup("html5") is HTML5everTreeBuilder
    assert registry.lookup("html") is HTML5everTreeBuilder
    assert registry.lookup("xml") is None


def test_register_is_idempotent():
    before = {k: list(v) for k, v in builder_registry.builders_for_feature.items()}
    soup5ever.register()
    soup5ever.register()
    after = {k: list(v) for k, v in builder_registry.builders_for_feature.items()}
    assert before == after


def test_builder_capabilities():
    builder = HTML5everTreeBuilder()
    assert builder.is_xml is False
    assert builder.TRACKS_LINE_NUMBERS is True
    assert {"html5ever", "html5", "html", "permissive"} <= set(builder.features)


def test_builder_class_argument():
    assert soup("<p>x").p.string == "x"
    assert BeautifulSoup("<p>x", builder=HTML5everTreeBuilder).p.string == "x"
    assert BeautifulSoup("<p>x", builder=HTML5everTreeBuilder()).p.string == "x"


# --- object types ----------------------------------------------------------


def test_ordinary_bs4_objects():
    doc = soup("<!DOCTYPE html><!--c--><p class='a b'>t<svg xlink:href=x></svg>")
    assert type(doc) is BeautifulSoup
    doctype, comment, html = doc.contents
    assert type(doctype) is Doctype and doctype == "html"
    assert type(comment) is Comment and comment == "c"
    assert type(html) is Tag
    assert type(doc.p.contents[0]) is NavigableString
    assert doc.p["class"] == ["a", "b"]
    [key] = doc.svg.attrs
    assert type(key) is NamespacedAttribute
    assert (key.prefix, key.name, key.namespace) == ("xlink", "href", "http://www.w3.org/1999/xlink")


def test_xmlns_attribute_prefix_is_none():
    # Regression: html5ever reports an empty prefix for `xmlns`; html5lib
    # (and NamespacedAttribute's convention) use None.
    [key] = soup("<svg xmlns=http://www.w3.org/2000/svg>").svg.attrs
    assert key.prefix is None and key == "xmlns"
    assert canon.canonical(soup("<svg xmlns=a>")) == canon.canonical(html5lib("<svg xmlns=a>"))


def test_custom_element_classes():
    class MyTag(Tag):
        pass

    class MyString(NavigableString):
        pass

    class MyComment(Comment):
        pass

    doc = soup(
        "<p>x<!--y-->",
        element_classes={Tag: MyTag, NavigableString: MyString, Comment: MyComment},
    )
    assert type(doc.p) is MyTag
    assert type(doc.p.contents[0]) is MyString
    assert type(doc.p.contents[1]) is MyComment


def test_custom_attribute_dict_setitem_is_used():
    # Regression (found by BS4's smoke test): attributes must go through the
    # attribute dict's __setitem__, as with html5lib.
    class Upper(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value.upper() if isinstance(value, str) else value)

    builder = HTML5everTreeBuilder(attribute_dict_class=Upper)
    doc = BeautifulSoup("<a href=x title=y>", builder=builder)
    assert doc.a.attrs == {"href": "X", "title": "Y"}


def test_multi_valued_attributes_none():
    doc = soup("<p class=' a  b '>", multi_valued_attributes=None)
    assert doc.p["class"] == " a  b "


def test_strings_are_plain_navigablestrings():
    # Same as html5lib: no Script/Stylesheet/TemplateString subclasses.
    doc = soup("<style>a</style><script>b</script><template>c</template>")
    for string in doc.find_all(string=True):
        assert type(string) is NavigableString


def test_template_contents_are_children():
    doc = soup("<template><p>x</p></template>")
    template = doc.head.template
    assert [c.name for c in template.contents] == ["p"]
    assert template.p.parent is template


def test_doctype_ids():
    # Regression: an empty public/system identifier is kept distinct from a
    # missing one (html5ever's TreeSink API loses that distinction).
    cases = {
        "<!DOCTYPE html>": "html",
        '<!DOCTYPE html PUBLIC "">': 'html PUBLIC ""',
        "<!DOCTYPE html SYSTEM ''>": 'html SYSTEM ""',
        '<!DOCTYPE html PUBLIC "a" "b">': 'html PUBLIC "a" "b"',
        "<!DOCTYPE>": "",
    }
    for markup, expected in cases.items():
        assert soup(markup).contents[0] == expected
        assert html5lib(markup).contents[0] == expected


def test_duplicate_attributes_keep_first():
    assert soup('<b a="1" a="2" A="3">').b.attrs == {"a": "1"}


def test_null_characters():
    doc = soup("<p>a\x00b</p><svg>\x00</svg>")
    assert doc.p.string == "ab"
    assert doc.svg.string == "�"


def test_lone_surrogates_become_replacement_characters():
    # Intentional difference: Rust strings can't hold lone surrogates, so
    # they become U+FFFD; html5lib passes them through.
    assert soup("<p>\ud800x\udfff</p>").p.string == "�x�"


def test_bom_in_str_is_content():
    assert soup("﻿<p>x").body.contents[0] == "﻿"


def test_deep_nesting_does_not_recurse():
    depth = 3000
    doc = soup("<div>" * depth)
    assert len(doc.find_all("div")) == depth
    assert canon.linkage_problems(doc) == []


# --- tree navigation -------------------------------------------------------


def test_navigation_after_reparenting():
    doc = soup("<p><em>foo</p>\n<p>bar<a></a></em></p>")
    assert canon.linkage_problems(doc) == []
    assert [e.name for e in doc.find_all(True)] == [
        "html", "head", "body", "p", "em", "em", "p", "em", "a",
    ]
    last = doc.find_all("a")[-1]
    assert list(last.parents)[-1] is doc
    assert doc._most_recent_element is last


def test_tree_modification_after_parse():
    doc = soup("<table><td>a</td></table><p>b")
    doc.p.extract()
    doc.td.append(doc.new_tag("b"))
    doc.body.insert(0, "start")
    assert canon.linkage_problems(doc) == []
    assert str(doc.body) == "<body>start<table><tbody><tr><td>a<b></b></td></tr></tbody></table></body>"


def test_pickle_and_copy():
    doc = soup("<p class='a b'>x<b>y</b></p><svg xlink:href=z></svg>")
    clone = pickle.loads(pickle.dumps(doc))
    assert canon.canonical(clone) == canon.canonical(doc)
    assert type(clone.builder) is HTML5everTreeBuilder
    # (copy.deepcopy of a whole BeautifulSoup object loses <body>'s children
    # with BS4 4.15 regardless of the builder; copy a tag instead.)
    assert canon.canonical(copy.deepcopy(doc.body)) == canon.canonical(doc.body)


def test_css_select():
    pytest.importorskip("soupsieve")
    doc = soup("<ul><li class=a>1<li class='a b'>2<li>3</ul>")
    assert [li.string for li in doc.select("li.a")] == ["1", "2"]


# --- source positions ------------------------------------------------------


def test_positions_match_html5lib():
    markup = "\n   <p>\n\n<sourceline>\n<b>text</b></sourceline><sourcepos></p>"
    ours, theirs = soup(markup), html5lib(markup)
    assert [(t.name, t.sourceline, t.sourcepos) for t in ours.find_all(True)] == [
        (t.name, t.sourceline, t.sourcepos) for t in theirs.find_all(True)
    ]


def test_positions_crlf_and_non_ascii():
    markup = "a\r\nb\rc<p>é\U0001F600<b>"
    ours, theirs = soup(markup), html5lib(markup)
    assert (ours.b.sourceline, ours.b.sourcepos) == (theirs.b.sourceline, theirs.b.sourcepos) == (3, 8)


def test_positions_of_implied_elements():
    # Regression: elements implied by leading text get the text's end
    # position, as in html5lib (which hands the run over at '<' or '&').
    for markup in ["FOO<!-- x -->", "FOO&amp;BAR", "hello"]:
        ours, theirs = soup(markup), html5lib(markup)
        assert (ours.html.sourceline, ours.html.sourcepos) == (
            theirs.html.sourceline,
            theirs.html.sourcepos,
        )


def test_adoption_agency_clones_have_no_position():
    # Regression: html5lib creates the adoption agency's copies with
    # cloneNode(), which records no position; reconstructed formatting
    # elements do get one.
    for markup in ["<a>1<p>2</a>3</p>", "<b>1<p>2</b>3</p>", "<table><a>1<td>2</td>3</table>"]:
        ours, theirs = soup(markup), html5lib(markup)
        assert [(t.name, t.sourceline, t.sourcepos) for t in ours.find_all(True)] == [
            (t.name, t.sourceline, t.sourcepos) for t in theirs.find_all(True)
        ]


def test_store_line_numbers_false():
    doc = soup("<p>x", store_line_numbers=False)
    assert doc.p.sourceline is None and doc.p.sourcepos is None


# --- encodings -------------------------------------------------------------


def test_str_has_no_original_encoding():
    assert soup("<meta charset=sjis><p>x").original_encoding is None


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"<p>ascii", "windows-1252"),
        (b"\xef\xbb\xbf<p>\xc3\xa9", "utf-8"),
        ("<p>é".encode("utf-16-le").join([b"\xff\xfe", b""]), "utf-16le"),
        ("<p>é".encode("utf-16-be").join([b"\xfe\xff", b""]), "utf-16be"),
        (b'<meta charset="iso-8859-2"><p>\xb1', "iso-8859-2"),
        (b"<meta http-equiv=Content-Type content='text/html; charset=sjis'><p>\x82\xa0", "shift_jis"),
        (b"<meta charset=latin1><p>\xe9", "windows-1252"),
        (b"<meta charset=utf-16><p>x", "utf-8"),
        (b"<meta charset=bogus><p>x", "windows-1252"),
    ],
)
def test_encoding_matches_html5lib(data, expected):
    ours, theirs = soup(data), html5lib(data)
    assert ours.original_encoding == theirs.original_encoding == expected
    assert canon.canonical(ours) == canon.canonical(theirs)


def test_meta_after_prescan_window_reparses():
    # The prescan only looks at 1024 bytes; a later <meta charset> makes the
    # tree builder change the (tentative) encoding and re-parse.
    data = b"<!--" + b"x" * 1100 + b'--><meta charset="iso-8859-2"><p>\xb1'
    ours, theirs = soup(data), html5lib(data)
    assert ours.original_encoding == theirs.original_encoding == "iso-8859-2"
    assert ours.p.string == theirs.p.string == "ą"


def test_from_encoding_overrides_meta():
    data = b'<meta charset="iso-8859-2"><p>\xb1'
    ours, theirs = soup(data, from_encoding="windows-1252"), html5lib(data, from_encoding="windows-1252")
    assert ours.original_encoding == theirs.original_encoding == "windows-1252"
    assert ours.p.string == "\xb1"


def test_from_encoding_accepts_python_codec_names():
    # "latin-1" isn't a WHATWG label; html5lib would ignore it.
    assert soup(b"<p>\xe9", from_encoding="latin-1").original_encoding == "windows-1252"
    assert soup("<p>é".encode(), from_encoding="utf_8").original_encoding == "utf-8"


def test_bom_beats_from_encoding():
    data = b"\xef\xbb\xbf<p>\xc3\xa9"
    assert soup(data, from_encoding="iso-8859-2").original_encoding == "utf-8"


def test_utf8_without_declaration():
    # Intentional difference: undeclared, valid UTF-8 is decoded as UTF-8.
    # html5lib guesses windows-1252 unless chardet is installed.
    data = "<p>naïve café ✓</p>".encode()
    doc = soup(data)
    assert doc.original_encoding == "utf-8"
    assert doc.p.string == "naïve café ✓"


def test_windows_1252_c1_bytes_follow_whatwg():
    # Intentional difference: WHATWG windows-1252 maps 0x81 to U+0081;
    # Python's cp1252 codec (used by html5lib) has no mapping for it.
    assert soup(b"<p>\x81\x80").p.string == "\x81€"


def test_file_input(tmp_path):
    path = tmp_path / "doc.html"
    path.write_bytes(b"<p>file")
    with path.open("rb") as f:
        assert soup(f).p.string == "file"
    with path.open("r") as f:
        assert soup(f).p.string == "file"


def test_rejects_other_types():
    with pytest.raises(TypeError):
        soup(12)


# --- warnings --------------------------------------------------------------


def test_xml_warning():
    from bs4.builder import XMLParsedAsHTMLWarning

    with pytest.warns(XMLParsedAsHTMLWarning):
        soup('<?xml version="1.0"?><root><child/></root>')


def test_parse_only_warns():
    from bs4.filter import SoupStrainer

    with pytest.warns(UserWarning, match="parse_only"):
        doc = soup("<p>a<b>b</b>", parse_only=SoupStrainer("b"))
    assert doc.p is not None


# --- threads ---------------------------------------------------------------


def test_parsing_from_threads():
    markup = "<table>" + "<tr><td>x<b>y</td></tr>" * 500 + "</table>"
    expected = canon.canonical(soup(markup))
    results = []

    def work():
        results.append(canon.canonical(soup(markup)))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [expected] * 8
