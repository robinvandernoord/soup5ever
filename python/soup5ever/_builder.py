"""The BeautifulSoup `TreeBuilder` for html5ever."""

from __future__ import annotations

import codecs
import gc
import re
import warnings
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

import bs4
from bs4.builder import (
    HTML,
    HTML_5,
    PERMISSIVE,
    DetectsXMLParsedAsHTML,
    HTMLTreeBuilder,
    TreeBuilder,
    TreeBuilderRegistry,
    builder_registry,
    nonwhitespace_re,
)
from bs4.element import (
    AttributeDict,
    Comment,
    Doctype,
    HTMLAttributeDict,
    NamespacedAttribute,
    NavigableString,
    PageElement,
    Tag,
)

from . import _soup5ever

if TYPE_CHECKING:
    from bs4._typing import _Encoding, _Encodings, _RawMarkup

__all__ = ["HTML5everExperimentalTreeBuilder", "HTML5everTreeBuilder", "register"]


class HTML5everTreeBuilder(HTMLTreeBuilder):
    """Build a BeautifulSoup tree with html5ever (https://github.com/servo/html5ever).

    The whole document is parsed in Rust (with the GIL released); the
    finished tree is then turned into ordinary BeautifulSoup objects in a
    single pass. The behavioral reference is BeautifulSoup's `html5lib`
    tree builder, and like it this builder:

    * does not support `parse_only` (a warning is issued and the whole
      document is parsed);
    * puts every string in a plain `NavigableString` (no `Script`,
      `Stylesheet`, ... subclasses);
    * records `sourceline`/`sourcepos` for each tag.
    """

    NAME = "html5ever"
    ALTERNATE_NAMES = ["soup5ever"]

    # The html5ever feature names are claimed outright. The generic ones are
    # advertised (so lookups for them can find this builder) but registered
    # at the lowest priority; see `register`.
    features: Iterable[str] = [NAME, "soup5ever", PERMISSIVE, HTML_5, HTML]

    TRACKS_LINE_NUMBERS = True

    # Whether to create BS4 objects without their constructors; see
    # `HTML5everExperimentalTreeBuilder`.
    _DIRECT_CONSTRUCTION = False

    user_specified_encoding: str | None = None

    def prepare_markup(
        self,
        markup: _RawMarkup,
        user_specified_encoding: _Encoding | None = None,
        document_declared_encoding: _Encoding | None = None,
        exclude_encodings: _Encodings | None = None,
    ) -> Iterator[tuple[_RawMarkup, _Encoding | None, _Encoding | None, bool]]:
        self.user_specified_encoding = user_specified_encoding
        for value, name in (
            (document_declared_encoding, "document_declared_encoding"),
            (exclude_encodings, "exclude_encodings"),
        ):
            if value:
                warnings.warn(
                    f"You provided a value for {name}, but the html5ever tree builder doesn't support {name}.",
                    stacklevel=3,
                )
        DetectsXMLParsedAsHTML.warn_if_markup_looks_like_xml(markup, stacklevel=3)
        yield (markup, None, None, False)

    def feed(self, markup: _RawMarkup) -> None:
        soup = self.soup
        assert soup is not None
        if soup.parse_only is not None:
            warnings.warn(
                "You provided a value for parse_only, but the html5ever tree builder "
                "doesn't support parse_only. The entire document will be parsed.",
                stacklevel=4,
            )
        element_classes = soup.element_classes
        classes = {
            "tag": element_classes.get(Tag, Tag),
            "string": element_classes.get(NavigableString, NavigableString),
            "comment": element_classes.get(Comment, Comment),
            "doctype": Doctype,
            "namespaced_attribute": NamespacedAttribute,
            "attribute_dict": self.attribute_dict_class,
            "attribute_dict_is_plain": self.attribute_dict_class in _PLAIN_ATTRIBUTE_DICTS,
        }
        classes["direct"] = _direct_construction(self, classes) if self._DIRECT_CONSTRUCTION else None
        # Building the tree allocates one large graph of objects that stays
        # reachable, so collections triggered while it is being built can't
        # free anything; with the collector paused, the build is 25-30%
        # faster on large documents. A collector the caller disabled stays
        # disabled.
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()
        try:
            encoding = _soup5ever.build_tree(
                soup,
                self,
                markup,
                classes,
                encodings=_encoding_labels(self.user_specified_encoding),
                store_line_numbers=bool(self.store_line_numbers),
            )
        finally:
            if gc_was_enabled:
                gc.enable()
        soup.original_encoding = encoding

    def test_fragment_to_document(self, fragment: str) -> str:
        """See `TreeBuilder.test_fragment_to_document`."""
        return f"<html><head></head><body>{fragment}</body></html>"


def _encoding_labels(label: str | None) -> list[str]:
    """Candidate WHATWG labels for a user-supplied `from_encoding`.

    The label is tried as given first (so it means what it means to
    html5lib); if it isn't a WHATWG label, Python's canonical codec name is
    tried as well, so that e.g. `"latin-1"` or `"utf_8"` still work.
    """
    if not label:
        return []
    labels = [label]
    try:
        labels.append(codecs.lookup(label).name)
    except LookupError:
        pass
    return labels


class HTML5everExperimentalTreeBuilder(HTML5everTreeBuilder):
    """`HTML5everTreeBuilder`, but creating BeautifulSoup objects directly.

    Select it with `BeautifulSoup(markup, "html5ever-experimental")`. The
    trees are the same as `"html5ever"`'s, down to each object's attributes
    and their order; building them is 10-30% faster.

    Instead of calling `Tag.__init__` and `NavigableString.__new__` for every
    node, the extension sets the attributes those constructors would set,
    once each and already linked into the tree. That relies on BeautifulSoup
    internals, so this builder is experimental: it is checked against the
    installed BeautifulSoup (and falls back to the regular construction,
    with a warning, if that sets different attributes), but a BeautifulSoup
    release that changes what those attributes mean would go unnoticed.

    Direct construction is only used when every class and builder method
    involved is BeautifulSoup's own; custom `element_classes` that change
    construction or attribute access (see `_is_bs4_page_element`),
    `attribute_dict_class`es with their own `__setitem__`, or builder
    subclasses that override how tags are set up get the regular
    construction, silently.
    """

    NAME = "html5ever-experimental"
    ALTERNATE_NAMES = ["soup5ever-experimental"]
    features: Iterable[str] = [NAME, "soup5ever-experimental", PERMISSIVE, HTML_5, HTML]

    _DIRECT_CONSTRUCTION = True


# What BS4's constructors set, in order, as of 4.13-4.15. Direct construction
# sets exactly these; see `_bs4_supports_direct_construction`.
_TAG_ATTRIBUTES = (
    "parser_class", "name", "namespace", "_namespaces", "prefix", "sourceline", "sourcepos",
    "attribute_value_list_class", "attrs", "known_xml", "contents", "parent", "previous_element",
    "next_element", "next_sibling", "previous_sibling", "hidden", "can_be_empty_element",
    "cdata_list_attributes", "preserve_whitespace_tags", "interesting_string_types",
)  # fmt: skip
_STRING_ATTRIBUTES = ("hidden", "parent", "previous_element", "next_element", "next_sibling", "previous_sibling")

_bs4_supported: bool | None = None


def _bs4_supports_direct_construction() -> bool:
    """Whether the installed BS4 builds objects the way direct construction does.

    Checked once: BS4's constructors must set exactly the attributes direct
    construction sets, and multi-valued attributes must be split on the
    whitespace the extension splits on.
    """
    global _bs4_supported
    if _bs4_supported is None:
        tag = Tag(None, HTMLTreeBuilder(), "p", None, None, {"class": "a b"})
        _bs4_supported = (
            nonwhitespace_re.pattern == r"\S+"
            and nonwhitespace_re.flags == re.UNICODE
            and tuple(vars(tag)) == _TAG_ATTRIBUTES
            and tuple(vars(NavigableString("x"))) == _STRING_ATTRIBUTES
        )
        if not _bs4_supported:
            warnings.warn(
                f"html5ever-experimental: BeautifulSoup {bs4.__version__} builds its objects differently "
                "from what soup5ever expects; falling back to html5ever's regular (slower) construction.",
                stacklevel=6,
            )
    return _bs4_supported


def _is_bs4_page_element(cls: type, base: type, attributes: tuple[str, ...]) -> bool:
    """Whether creating a `cls` runs only `base`'s own BS4 code.

    Besides the constructors, that covers attribute access: `Tag.__init__`
    and `PageElement.setup` read some of the attributes they have just set
    (`name`, `parent`, ...), so a custom `__getattribute__`, or a property
    (any data descriptor) for one of `attributes` in a class added on top of
    `base`, can change what they compute. `__getattr__` can't: it only runs
    for attributes that don't exist, and every one read has been set.
    """
    return (
        issubclass(cls, base)
        and type(cls) is type
        and cls.__new__ is base.__new__
        and cls.__init__ is base.__init__
        and cls.__setattr__ is object.__setattr__
        and cls.__getattribute__ is object.__getattribute__
        and cls.setup is PageElement.setup
        and not any(
            _is_data_descriptor(klass.__dict__[name])
            for klass in cls.__mro__
            if klass not in base.__mro__
            for name in attributes
            if name in klass.__dict__
        )
    )


def _is_data_descriptor(value: object) -> bool:
    return hasattr(type(value), "__set__") or hasattr(type(value), "__delete__")


def _direct_construction(builder: HTML5everTreeBuilder, classes: dict) -> dict | None:
    """The extension's `direct` config, or None if something user-defined would be skipped."""
    builder_type = type(builder)
    if not (
        classes["attribute_dict_is_plain"]
        and _is_bs4_page_element(classes["tag"], Tag, _TAG_ATTRIBUTES)
        and _is_bs4_page_element(classes["string"], NavigableString, _STRING_ATTRIBUTES)
        and _is_bs4_page_element(classes["comment"], NavigableString, _STRING_ATTRIBUTES)
        and builder_type.can_be_empty_element is TreeBuilder.can_be_empty_element
        and builder_type.set_up_substitutions is HTMLTreeBuilder.set_up_substitutions
        and builder_type._replace_cdata_list_attribute_values is TreeBuilder._replace_cdata_list_attribute_values
        and _bs4_supports_direct_construction()
    ):
        return None
    cdata_list_attributes = builder.cdata_list_attributes
    string_containers = builder.string_containers

    def name_info(name: str) -> tuple[bool, type | None, frozenset | None]:
        # What `Tag.__init__` asks the builder about a tag name, and which of
        # its attributes `_replace_cdata_list_attribute_values` would split.
        multi_valued = None
        if cdata_list_attributes:
            multi_valued = frozenset(cdata_list_attributes.get("*", ())) | frozenset(
                cdata_list_attributes.get(name.lower()) or ()
            )
        return (
            builder.can_be_empty_element(name),
            string_containers[name] if name in string_containers else None,
            multi_valued or None,
        )

    return {
        "object_new": object.__new__,
        "str_new": str.__new__,
        "name_info": name_info,
        "attribute_value_list_class": builder.attribute_value_list_class,
        "known_xml": builder.is_xml,
        "cdata_list_attributes": cdata_list_attributes,
        "preserve_whitespace_tags": builder.preserve_whitespace_tags,
        "main_content_string_types": classes["tag"].MAIN_CONTENT_STRING_TYPES,
        "set_up_substitutions": builder.set_up_substitutions,
    }


# Attribute dict classes whose `__setitem__` stores a str value unchanged, so
# the extension may fill them with plain dict operations.
_PLAIN_ATTRIBUTE_DICTS = (dict, AttributeDict, HTMLAttributeDict)

_BUILDERS = (HTML5everTreeBuilder, HTML5everExperimentalTreeBuilder)
_EXCLUSIVE_FEATURES = frozenset(name for cls in _BUILDERS for name in (cls.NAME, *cls.ALTERNATE_NAMES))


def register(registry: TreeBuilderRegistry = builder_registry) -> None:
    """Register soup5ever's builders with a BeautifulSoup builder registry.

    Called when `soup5ever` is imported; calling it again is harmless.

    `TreeBuilderRegistry.register` gives the newest builder the highest
    priority for *every* feature it lists, which would make importing
    soup5ever silently change what `BeautifulSoup(markup, "html5")` or
    `BeautifulSoup(markup, "html")` mean. Instead, each builder is put first
    only for its own names (`"html5ever"`, `"soup5ever"`,
    `"html5ever-experimental"`, ...) and last for the generic ones, so they
    keep selecting whichever builder they selected before, and fall back to
    (non-experimental) html5ever only when nothing else provides them.
    """
    for cls in _BUILDERS:
        for feature in cls.features:
            builders = registry.builders_for_feature[feature]
            if cls in builders:
                continue
            if feature in _EXCLUSIVE_FEATURES:
                builders.insert(0, cls)
            else:
                builders.append(cls)
        if cls not in registry.builders:
            registry.builders.append(cls)
