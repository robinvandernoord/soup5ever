"""html5lib's own (minidom) tree in html5lib-tests format.

Used to tell apart html5lib *parser* behavior from quirks of BeautifulSoup's
html5lib *adapter* (``bs4.builder._html5lib``) when classifying differences.
"""

from __future__ import annotations

import html5lib
from html5lib.treebuilders import getTreeBuilder

from .canon import HTML_NS, NS_PREFIXES

_ATTR_PREFIXES = {
    "http://www.w3.org/1999/xlink": "xlink",
    "http://www.w3.org/XML/1998/namespace": "xml",
    "http://www.w3.org/2000/xmlns/": "xmlns",
}


def to_test_format(markup) -> str:
    parser = html5lib.HTMLParser(tree=getTreeBuilder("dom"))
    doc = parser.parse(markup)
    lines: list[str] = []

    def walk(node, depth):
        indent = "| " + "  " * depth
        t = node.nodeType
        if t == node.DOCUMENT_TYPE_NODE:
            if node.publicId is None and node.systemId is None:
                lines.append(f"{indent}<!DOCTYPE {node.name or ''}>")
            else:
                lines.append(
                    f'{indent}<!DOCTYPE {node.name or ""} "{node.publicId or ""}" '
                    f'"{node.systemId or ""}">'
                )
        elif t == node.COMMENT_NODE:
            lines.append(f"{indent}<!-- {node.data} -->")
        elif t == node.TEXT_NODE:
            lines.append(f'{indent}"{node.data}"')
        elif t == node.ELEMENT_NODE:
            prefix = NS_PREFIXES.get(node.namespaceURI, node.namespaceURI)
            name = node.localName or node.tagName
            lines.append(f"{indent}<{prefix + ' ' if prefix else ''}{name}>")
            attrs = []
            for i in range(node.attributes.length):
                a = node.attributes.item(i)
                if a.namespaceURI in _ATTR_PREFIXES:
                    key = f"{_ATTR_PREFIXES[a.namespaceURI]} {a.localName}"
                else:
                    key = a.name
                attrs.append((key, a.value))
            attr_indent = "| " + "  " * (depth + 1)
            for key, value in sorted(attrs):
                lines.append(f'{attr_indent}{key}="{value}"')
            child_depth = depth + 1
            if name == "template" and node.namespaceURI == HTML_NS:
                lines.append(f"{attr_indent}content")
                child_depth += 1
            for child in node.childNodes:
                walk(child, child_depth)

    for child in doc.childNodes:
        walk(child, 0)
    return "\n".join(lines)
