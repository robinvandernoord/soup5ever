"""A BeautifulSoup tree builder backed by Rust's html5ever HTML5 parser.

Importing this module registers the `"html5ever"` parser feature:

    from bs4 import BeautifulSoup
    import soup5ever

    soup = BeautifulSoup(html, "html5ever")

`"html5ever-experimental"` builds the same trees faster by relying on
BeautifulSoup internals; see `HTML5everExperimentalTreeBuilder`.
"""

from __future__ import annotations

from ._builder import HTML5everExperimentalTreeBuilder, HTML5everTreeBuilder, register
from ._soup5ever import HTML5EVER_VERSION

__all__ = ["HTML5everExperimentalTreeBuilder", "HTML5everTreeBuilder", "HTML5EVER_VERSION", "register", "__version__"]

try:
    from importlib.metadata import version as _version

    __version__ = _version("soup5ever")
except Exception:  # pragma: no cover - not installed as a distribution
    __version__ = "0+unknown"

register()
