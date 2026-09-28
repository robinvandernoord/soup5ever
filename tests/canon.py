"""Canonical representations of BeautifulSoup trees, for comparing builders.

Serialized HTML hides too much (a NamespacedAttribute and a plain "a:b"
attribute serialize the same; so do a Comment and a NavigableString holding
"<!--x-->" in some formatters), so comparisons use explicit structures:

* `canonical` - a nested tuple capturing node type, tag name, namespace,
  prefix, attributes (with namespace details and list-ness), text, and child
  order.
* `to_test_format` - the html5lib-tests "#document" format, for comparing
  against the spec-level expectations in the html5lib-tests corpus.
* `linkage_problems` - checks that `next_element`/`previous_element`,
  sibling and parent pointers agree with `.contents`.
"""

from __future__ import annotations

import contextlib

from bs4 import BeautifulSoup
from bs4.element import (
    Comment,
    Doctype,
    NamespacedAttribute,
    NavigableString,
    PageElement,
    Tag,
)

HTML_NS = "http://www.w3.org/1999/xhtml"
NS_PREFIXES = {
    HTML_NS: None,
    "http://www.w3.org/2000/svg": "svg",
    "http://www.w3.org/1998/Math/MathML": "math",
}


def _attr_key(name):
    if isinstance(name, NamespacedAttribute):
        return (str(name), "ns", name.prefix, name.name, name.namespace)
    return (str(name), "plain")


def _attr_value(value):
    if isinstance(value, list):
        return ("list", tuple(value))
    return (type(value).__name__, str(value))


def canonical(node: PageElement, *, attr_order: bool = False, positions: bool = False):
    """A hashable, comparable structure for `node` and its descendants."""
    if isinstance(node, Tag):
        attrs = [(_attr_key(k), _attr_value(v)) for k, v in node.attrs.items()]
        if not attr_order:
            attrs.sort()
        children = tuple(
            canonical(c, attr_order=attr_order, positions=positions) for c in node.contents
        )
        if isinstance(node, BeautifulSoup):
            return ("document", children)
        extra = (node.sourceline, node.sourcepos) if positions else ()
        return ("tag", node.namespace, node.prefix, node.name, tuple(attrs), children) + extra
    assert isinstance(node, NavigableString), type(node)
    return (type(node).__name__, str(node))


def _format_attr(name) -> str:
    if isinstance(name, NamespacedAttribute) and name.prefix and name.name:
        return f"{name.prefix} {name.name}"
    return str(name)


def to_test_format(soup: BeautifulSoup) -> str:
    """Serialize like html5lib-tests' expected "#document" output.

    Use a soup parsed with ``multi_valued_attributes=None`` so attribute
    values are the raw strings.
    """
    lines: list[str] = []

    def walk(node: PageElement, depth: int) -> None:
        indent = "| " + "  " * depth
        if isinstance(node, Doctype):
            lines.append(f"{indent}{_format_doctype(str(node))}")
        elif isinstance(node, Comment):
            lines.append(f"{indent}<!-- {node} -->")
        elif isinstance(node, NavigableString):
            lines.append(f'{indent}"{node}"')
        elif isinstance(node, Tag):
            prefix = NS_PREFIXES.get(node.namespace, node.namespace)
            name = f"{prefix} {node.name}" if prefix else node.name
            lines.append(f"{indent}<{name}>")
            attr_indent = "| " + "  " * (depth + 1)
            for key, value in sorted(
                ((_format_attr(k), v) for k, v in node.attrs.items()), key=lambda kv: kv[0]
            ):
                if isinstance(value, list):
                    value = " ".join(value)
                lines.append(f'{attr_indent}{key}="{value}"')
            child_depth = depth + 1
            if node.name == "template" and node.namespace == HTML_NS:
                lines.append(f"{attr_indent}content")
                child_depth += 1
            for child in node.contents:
                walk(child, child_depth)

    for child in soup.contents:
        walk(child, 0)
    return "\n".join(lines)


def _format_doctype(value: str) -> str:
    """Doctype.for_name_and_ids output -> html5lib-tests doctype line."""
    name, public, system = value, None, None
    if ' PUBLIC "' in value:
        name, rest = value.split(' PUBLIC "', 1)
        if '" "' in rest:
            public, system = rest.split('" "', 1)
            system = system[:-1]
        else:
            public = rest[:-1]
    elif ' SYSTEM "' in value:
        name, rest = value.split(' SYSTEM "', 1)
        system = rest[:-1]
    if public is None and system is None:
        return f"<!DOCTYPE {name}>"
    return f'<!DOCTYPE {name} "{public or ""}" "{system or ""}">'


def linkage_problems(soup: BeautifulSoup) -> list[str]:
    """Inconsistencies between `.contents` and the navigation pointers."""
    problems: list[str] = []
    order = list(soup.descendants)
    # Builders differ on whether the soup object itself starts the chain
    # (html5lib links it to the first node unless that is a doctype); both
    # are accepted as long as the two ends agree.
    head = soup if order and order[0].previous_element is soup else None
    if soup.next_element is not (order[0] if head is soup else None):
        problems.append(f"soup.next_element is {soup.next_element!r:.40}")
    for i, node in enumerate(order):
        expected_next = order[i + 1] if i + 1 < len(order) else None
        if node.next_element is not expected_next:
            problems.append(f"{node!r:.40}.next_element is {node.next_element!r:.40}")
        expected_prev = order[i - 1] if i > 0 else head
        if node.previous_element is not expected_prev:
            problems.append(f"{node!r:.40}.previous_element is {node.previous_element!r:.40}")
    stack = [soup]
    while stack:
        tag = stack.pop()
        for i, child in enumerate(tag.contents):
            if child.parent is not tag:
                problems.append(f"{child!r:.40}.parent is not its container")
            prev = tag.contents[i - 1] if i else None
            nxt = tag.contents[i + 1] if i + 1 < len(tag.contents) else None
            if child.previous_sibling is not prev:
                problems.append(f"{child!r:.40}.previous_sibling is wrong")
            if child.next_sibling is not nxt:
                problems.append(f"{child!r:.40}.next_sibling is wrong")
            if isinstance(child, Tag):
                stack.append(child)
    return problems


@contextlib.contextmanager
def html5lib_adapter_fixed():
    """Temporarily fix the one BS4 html5lib-adapter bug that affects trees.

    html5lib's Noah's Ark clause decides whether two formatting elements are
    "the same" with ``node1.attributes == node2.attributes``. BS4's adapter
    returns a fresh ``AttrList`` (which has no ``__eq__``) on every access,
    so the comparison is always False. With this patch the html5lib builder
    is a clean reference for inputs that happen to trigger that bug.
    """
    from bs4.builder._html5lib import AttrList

    def __eq__(self, other):
        return isinstance(other, AttrList) and self.attrs == other.attrs

    AttrList.__eq__ = __eq__
    AttrList.__hash__ = None
    try:
        yield
    finally:
        del AttrList.__eq__
        del AttrList.__hash__


def diff(a, b, path="") -> str | None:
    """Describe the first difference between two `canonical` structures."""
    if a == b:
        return None
    if (
        isinstance(a, tuple)
        and isinstance(b, tuple)
        and a[:1] == b[:1]
        and a[0] in ("tag", "document")
    ):
        head_a, head_b = a[:-1] if a[0] == "document" else a[:5], b[:-1] if b[0] == "document" else b[:5]
        if head_a != head_b:
            return f"{path}: {head_a!r} != {head_b!r}"
        ca, cb = a[-1] if a[0] == "document" else a[5], b[-1] if b[0] == "document" else b[5]
        name = a[3] if a[0] == "tag" else "#document"
        for i, (x, y) in enumerate(zip(ca, cb)):
            d = diff(x, y, f"{path}/{name}[{i}]")
            if d:
                return d
        if len(ca) != len(cb):
            return f"{path}/{name}: {len(ca)} children != {len(cb)}: {ca[len(cb):]!r:.200} / {cb[len(ca):]!r:.200}"
        if a[0] == "tag" and a[6:] != b[6:]:
            return f"{path}/{name}: position {a[6:]} != {b[6:]}"
    return f"{path}: {a!r:.200} != {b!r:.200}"
