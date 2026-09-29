"""The `html5ever-experimental` builder: same trees as `html5ever`, built directly.

`HTML5everExperimentalTreeBuilder` creates BS4 objects without running their
constructors. The contract is that nothing observable changes, so the main
check here compares the complete state of every object (`vars()` in order,
value types, which node each link points to, shared vs fresh containers)
against `html5ever`'s, over every input the other suites use. Since
`html5ever` itself is checked against html5lib and the spec elsewhere, that
carries every other guarantee over.

The rest checks when direct construction is (and isn't) used, and that it
really is used: otherwise the comparison would be vacuous.
"""

from __future__ import annotations

import warnings

import pytest
from bs4 import BeautifulSoup
from bs4.builder import builder_registry
from bs4.element import AttributeValueList, Comment, NavigableString, Tag

import soup5ever
from benchmarks.documents import BENCHMARKS, TEST_DOCUMENTS
from soup5ever import HTML5everExperimentalTreeBuilder, HTML5everTreeBuilder, _builder

from . import fuzz, html5lib_dat
from .corpus import CASES

EXPERIMENTAL = "html5ever-experimental"


def parse(markup, parser, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return BeautifulSoup(markup, parser, **kwargs)


def _value(value, index):
    if isinstance(value, (Tag, NavigableString)):
        return ("node", index.get(id(value), "outside the tree"))
    if isinstance(value, dict):
        return (type(value), [(type(k), k, _value(v, index)) for k, v in value.items()])
    if isinstance(value, list):
        return (type(value), [_value(v, index) for v in value])
    if isinstance(value, (set, frozenset)):
        # BS4 shares Tag.MAIN_CONTENT_STRING_TYPES between tags but makes a
        # new set for string-container tags; keep that distinction.
        shared = value is Tag.MAIN_CONTENT_STRING_TYPES
        return (type(value), sorted(map(repr, value)), shared)
    if isinstance(value, str):
        return (type(value), str(value), getattr(value, "__dict__", None))
    if value is None or isinstance(value, (bool, int, type)):
        return (type(value), value)
    return (type(value),)  # e.g. the soup's builder: a new one per parse


def object_state(soup):
    """Everything about every object in the tree, in comparable form."""
    nodes = [soup, *soup.descendants]
    index = {id(node): i for i, node in enumerate(nodes)}
    return [
        (
            type(node),
            str(node) if isinstance(node, NavigableString) else None,
            list(vars(node)),
            # The soup's `builder` is the one difference by definition.
            {key: _value(value, index) for key, value in vars(node).items() if key != "builder"},
        )
        for node in nodes
    ]


def assert_same_objects(markup, **kwargs):
    expected = object_state(parse(markup, "html5ever", **kwargs))
    actual = object_state(parse(markup, EXPERIMENTAL, **kwargs))
    assert len(actual) == len(expected)
    for i, (want, got) in enumerate(zip(expected, actual)):
        assert got == want, f"node {i}"


# --- same objects as html5ever ----------------------------------------------

EDGE_CASES = {
    "meta-substitutions": (
        "<meta charset=iso-8859-1><meta http-equiv=Content-Type content='text/html; charset=x'><meta content=x>"
    ),
    "multi-valued": (
        "<p class='\x1ca\x1fb c　 d' accesskey='a b'><a rel=' x  y ' rev=''>"
        "<table><td headers='h1 h2'><th headers=h3></table><form accept-charset='a b'>"
    ),
    "foreign": "<svg><foreignObject class='a b'><a xlink:href=x xml:lang=en>t</a></foreignObject></svg>",
    "string-containers": "<script>a</script><style>b</style><template>c<p>d</template><ruby>x<rt>y<rp>z</ruby>",
    "empty-element-tags": "<br><hr><img src=x><input><p></p><col><wbr>",
    "doctype-and-comments": "<!--before--><!DOCTYPE html><!--head--><p>x<!--in--></p><!--after-->",
    "empty": "",
}

DOCUMENTS = {
    **{f"corpus:{k}": v for k, v in CASES.items()},
    **{f"edge:{k}": v for k, v in EDGE_CASES.items()},
    **{f"document:{k}": make() for k, make in TEST_DOCUMENTS.items()},
    **{f"benchmark:{k}": make() for k, (_, make) in BENCHMARKS.items()},
}


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_same_objects(name):
    assert_same_objects(DOCUMENTS[name])


@pytest.mark.parametrize("name", sorted(k for k in DOCUMENTS if not k.startswith("benchmark:")))
def test_same_objects_from_bytes(name):
    assert_same_objects(DOCUMENTS[name].encode("utf-8"))


OPTIONS = {
    "no-multi-valued-attributes": {"multi_valued_attributes": None},
    "custom-multi-valued-attributes": {"multi_valued_attributes": {"*": {"class", "data-x"}, "a": ["rel"]}},
    "no-line-numbers": {"store_line_numbers": False},
    "custom-string-containers": {"string_containers": {"p": NavigableString, "b": Comment}},
    "html-attribute-dict": {"attribute_dict_class": dict},
}


@pytest.mark.parametrize("option", sorted(OPTIONS))
@pytest.mark.parametrize("name", sorted({**{f"edge:{k}": v for k, v in EDGE_CASES.items()}, "document:normal": 0}))
def test_same_objects_with_options(option, name):
    markup = EDGE_CASES[name[5:]] if name.startswith("edge:") else TEST_DOCUMENTS["normal"]()
    assert_same_objects(markup, **OPTIONS[option])


def test_same_objects_on_html5lib_tests():
    cases = [case for case in html5lib_dat.all_cases() if case.applicable]
    if not cases:
        pytest.skip("html5lib-tests not downloaded (scripts/fetch_upstream_tests.py)")
    for case in cases:
        assert_same_objects(case.data)


def test_same_objects_on_fuzz_inputs(request):
    seed = request.config.getoption("--fuzz-seed")
    for iteration in range(request.config.getoption("--fuzz")):
        assert_same_objects(fuzz.input_for(seed, iteration))


def test_object_state_detects_differences(monkeypatch):
    # Guard against a comparison that can't fail: break one per-name fact.
    original = _builder._direct_construction

    def broken(builder, classes):
        config = original(builder, classes)
        name_info = config["name_info"]
        config["name_info"] = lambda name: (not name_info(name)[0], *name_info(name)[1:])
        return config

    monkeypatch.setattr(_builder, "_direct_construction", broken)
    with pytest.raises(AssertionError):
        assert_same_objects("<p>x<br>")


# --- when direct construction is used ---------------------------------------


def direct_config(markup="<p>", **kwargs):
    """The config the experimental builder hands the extension (None: regular construction)."""
    seen = []
    original = _builder._direct_construction

    def spy(builder, classes):
        seen.append(original(builder, classes))
        return seen[-1]

    _builder._direct_construction = spy
    try:
        parse(markup, EXPERIMENTAL, **kwargs)
    finally:
        _builder._direct_construction = original
    [config] = seen
    return config


def test_direct_construction_is_used_by_default():
    assert direct_config() is not None
    assert _builder._bs4_supports_direct_construction()


def test_html5ever_never_uses_direct_construction(monkeypatch):
    def fail(*args):
        raise AssertionError("html5ever must not use direct construction")

    monkeypatch.setattr(_builder, "_direct_construction", fail)
    assert BeautifulSoup("<p>x", "html5ever").p.string == "x"


def test_custom_element_classes_are_constructed():
    created = []

    class MyTag(Tag):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self.name)

    class MyString(NavigableString):
        def __new__(cls, value):
            created.append(str(value))
            return super().__new__(cls, value)

    doc = parse("<p>x", EXPERIMENTAL, element_classes={Tag: MyTag, NavigableString: MyString})
    assert type(doc.p) is MyTag and type(doc.p.string) is MyString
    assert created == ["html", "head", "body", "p", "x"]


def test_plain_subclasses_are_constructed_directly():
    # A subclass that only adds methods runs no code of its own when created.
    class MyTag(Tag):
        def shout(self):
            return self.name.upper()

    assert direct_config(element_classes={Tag: MyTag}) is not None
    assert parse("<p>", EXPERIMENTAL, element_classes={Tag: MyTag}).p.shout() == "P"


class RenamingTag(Tag):
    # `Tag.__init__` reads `self.name` back to pick `interesting_string_types`.
    def __getattribute__(self, key):
        value = object.__getattribute__(self, key)
        return "script" if key == "name" and value == "p" else value


class NamePropertyTag(Tag):
    @property
    def name(self):
        return "script" if self.__dict__["name"] == "p" else self.__dict__["name"]

    @name.setter
    def name(self, value):
        self.__dict__["name"] = value


class ParentReportingString(NavigableString):
    # `PageElement.setup` reads `self.parent` back.
    def __getattribute__(self, key):
        return object.__getattribute__(self, key)


class PreviousPropertyComment(Comment):
    previous_element = property(
        lambda self: self.__dict__.get("previous_element"),
        lambda self, value: self.__dict__.__setitem__("previous_element", value),
    )


class GetattrTag(Tag):
    # Only called for missing attributes: never during construction.
    def __getattr__(self, key):
        return None if key.startswith("_x") else super().__getattr__(key)


class ClassAttributeTag(Tag):
    # A plain class attribute is shadowed by the instance attribute.
    hidden = True


@pytest.mark.parametrize(
    "element_classes,direct",
    [
        ({Tag: RenamingTag}, False),
        ({Tag: NamePropertyTag}, False),
        ({NavigableString: ParentReportingString}, False),
        ({Comment: PreviousPropertyComment}, False),
        ({Tag: GetattrTag}, True),
        ({Tag: ClassAttributeTag}, True),
    ],
    ids=lambda value: value if isinstance(value, bool) else next(iter(value.values())).__name__,
)
def test_custom_attribute_access(element_classes, direct):
    markup = "<p class='a b'>x<!--c--></p><script>y</script>"
    assert (direct_config(markup, element_classes=element_classes) is not None) is direct
    expected = object_state(parse(markup, "html5ever", element_classes=element_classes))
    assert object_state(parse(markup, EXPERIMENTAL, element_classes=element_classes)) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"element_classes": {Tag: type("T", (Tag,), {"__init__": lambda self, *a, **k: Tag.__init__(self, *a, **k)})}},
        {
            "element_classes": {
                Tag: type("T", (Tag,), {"__setattr__": lambda self, k, v: object.__setattr__(self, k, v)})
            }
        },
        {"element_classes": {NavigableString: type("S", (NavigableString,), {"setup": NavigableString.setup})}},
        {
            "element_classes": {
                Comment: type("C", (Comment,), {"__new__": lambda cls, value: NavigableString.__new__(cls, value)})
            }
        },
    ],
    ids=["tag-init", "tag-setattr", "string-setup-copy-is-fine", "comment-new"],
)
def test_constructor_overrides_fall_back(kwargs):
    config = direct_config(**kwargs)
    # `setup` copied from PageElement is the same function: still direct.
    [cls] = kwargs["element_classes"].values()
    assert (config is not None) == (cls.__name__ == "S")


def test_custom_attribute_dict_falls_back():
    class Upper(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value.upper() if isinstance(value, str) else value)

    builder = HTML5everExperimentalTreeBuilder(attribute_dict_class=Upper)
    assert BeautifulSoup("<a href=x>", builder=builder).a.attrs == {"href": "X"}


@pytest.mark.parametrize(
    "method,value",
    [
        ("can_be_empty_element", lambda self, name: name == "p"),
        ("set_up_substitutions", lambda self, tag: False),
        ("_replace_cdata_list_attribute_values", lambda self, name, attrs: attrs),
    ],
)
def test_builder_overrides_fall_back(method, value):
    builder_class = type("Custom", (HTML5everExperimentalTreeBuilder,), {method: value})
    expected = BeautifulSoup("<p class='a b'><br>", builder=type("Custom", (HTML5everTreeBuilder,), {method: value}))
    actual = BeautifulSoup("<p class='a b'><br>", builder=builder_class)
    assert object_state(actual) == object_state(expected)


def test_unsupported_bs4_falls_back_with_a_warning(monkeypatch):
    monkeypatch.setattr(_builder, "_bs4_supported", None)
    monkeypatch.setattr(_builder, "_TAG_ATTRIBUTES", (*_builder._TAG_ATTRIBUTES, "attribute_from_the_future"))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc = BeautifulSoup("<p class='a b'>x", EXPERIMENTAL)
    [warning] = caught
    assert warning.filename == __file__
    assert "falling back to html5ever's regular (slower) construction" in str(warning.message)
    assert doc.p["class"] == ["a", "b"]
    # Checked once per process.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        BeautifulSoup("<p>", EXPERIMENTAL)
    assert caught == []


def test_multi_valued_attributes_split_on_python_whitespace():
    # U+001C..U+001F are whitespace to Python (and BS4's regex) but not to
    # Rust's `char::is_whitespace`.
    doc = parse("<p class='a\x1cb\x1dc\x1ed\x1fe f'>", EXPERIMENTAL)
    assert doc.p["class"] == ["a", "b", "c", "d", "e", "f"]
    assert type(doc.p["class"]) is AttributeValueList


# --- registration ------------------------------------------------------------


def test_feature_names():
    assert builder_registry.lookup("html5ever-experimental") is HTML5everExperimentalTreeBuilder
    assert builder_registry.lookup("soup5ever-experimental") is HTML5everExperimentalTreeBuilder
    assert builder_registry.lookup("html5ever-experimental", "html5") is HTML5everExperimentalTreeBuilder
    assert builder_registry.lookup("html5ever") is HTML5everTreeBuilder
    assert type(BeautifulSoup("<p>", EXPERIMENTAL).builder) is HTML5everExperimentalTreeBuilder


def test_generic_features_never_select_the_experimental_builder():
    from bs4.builder import TreeBuilderRegistry

    registry = TreeBuilderRegistry()
    soup5ever.register(registry)
    assert registry.lookup("html5") is HTML5everTreeBuilder
    assert registry.lookup("html") is HTML5everTreeBuilder
    assert registry.lookup() is HTML5everTreeBuilder
