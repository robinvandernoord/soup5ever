"""Private extension module; use ``BeautifulSoup(markup, "html5ever")``."""

from typing import Any

from bs4 import BeautifulSoup
from bs4.builder import TreeBuilder

HTML5EVER_VERSION: str

def build_tree(
    soup: BeautifulSoup,
    builder: TreeBuilder,
    markup: str | bytes,
    classes: dict[str, Any],
    *,
    encodings: list[str],
    store_line_numbers: bool,
) -> str | None: ...
def _parse_only(markup: str | bytes) -> int: ...
