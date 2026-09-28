"""The BeautifulSoup ``TreeBuilder`` for html5ever."""

from __future__ import annotations

import codecs
import gc
import warnings
from collections.abc import Iterable, Iterator

from bs4.builder import (
    HTML,
    HTML_5,
    PERMISSIVE,
    DetectsXMLParsedAsHTML,
    HTMLTreeBuilder,
    TreeBuilderRegistry,
    builder_registry,
)
from bs4.element import (
    AttributeDict,
    Comment,
    Doctype,
    HTMLAttributeDict,
    NamespacedAttribute,
    NavigableString,
    Tag,
)

from . import _soup5ever

__all__ = ["HTML5everTreeBuilder", "register"]


class HTML5everTreeBuilder(HTMLTreeBuilder):
    """Build a BeautifulSoup tree with `html5ever <https://github.com/servo/html5ever>`_.

    The whole document is parsed in Rust (with the GIL released); the
    finished tree is then turned into ordinary BeautifulSoup objects in a
    single pass. The behavioral reference is BeautifulSoup's ``html5lib``
    tree builder, and like it this builder:

    * does not support ``parse_only`` (a warning is issued and the whole
      document is parsed);
    * puts every string in a plain `NavigableString` (no `Script`,
      `Stylesheet`, ... subclasses);
    * records ``sourceline``/``sourcepos`` for each tag.
    """

    NAME = "html5ever"
    ALTERNATE_NAMES = ["soup5ever"]

    #: The html5ever feature names are claimed outright. The generic ones
    #: are advertised (so lookups for them can find this builder) but
    #: registered at the lowest priority; see `register`.
    features: Iterable[str] = [NAME, "soup5ever", PERMISSIVE, HTML_5, HTML]

    TRACKS_LINE_NUMBERS = True

    user_specified_encoding: str | None = None

    def prepare_markup(
        self,
        markup,
        user_specified_encoding=None,
        document_declared_encoding=None,
        exclude_encodings=None,
    ) -> Iterator[tuple]:
        self.user_specified_encoding = user_specified_encoding
        for value, name in (
            (document_declared_encoding, "document_declared_encoding"),
            (exclude_encodings, "exclude_encodings"),
        ):
            if value:
                warnings.warn(
                    f"You provided a value for {name}, but the html5ever tree builder "
                    f"doesn't support {name}.",
                    stacklevel=3,
                )
        DetectsXMLParsedAsHTML.warn_if_markup_looks_like_xml(markup, stacklevel=3)
        yield (markup, None, None, False)

    def feed(self, markup) -> None:
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
    """Candidate WHATWG labels for a user-supplied ``from_encoding``.

    The label is tried as given first (so it means what it means to
    html5lib); if it isn't a WHATWG label, Python's canonical codec name is
    tried as well, so that e.g. ``"latin-1"`` or ``"utf_8"`` still work.
    """
    if not label:
        return []
    labels = [label]
    try:
        labels.append(codecs.lookup(label).name)
    except LookupError:
        pass
    return labels


#: Attribute dict classes whose ``__setitem__`` stores a str value unchanged,
#: so the extension may fill them with plain dict operations.
_PLAIN_ATTRIBUTE_DICTS = (dict, AttributeDict, HTMLAttributeDict)

_EXCLUSIVE_FEATURES = frozenset({HTML5everTreeBuilder.NAME, "soup5ever"})


def register(registry: TreeBuilderRegistry = builder_registry) -> None:
    """Register `HTML5everTreeBuilder` with a BeautifulSoup builder registry.

    Called when ``soup5ever`` is imported; calling it again is harmless.

    ``TreeBuilderRegistry.register`` gives the newest builder the highest
    priority for *every* feature it lists, which would make importing
    soup5ever silently change what ``BeautifulSoup(markup, "html5")`` or
    ``BeautifulSoup(markup, "html")`` mean. Instead, this builder is put first
    only for its own names (``"html5ever"``, ``"soup5ever"``) and last for
    the generic ones, so they keep selecting whichever builder they selected
    before, and fall back to html5ever only when nothing else provides them.
    """
    cls = HTML5everTreeBuilder
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
