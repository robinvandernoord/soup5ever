# soup5ever

A [BeautifulSoup 4](https://www.crummy.com/software/BeautifulSoup/) tree builder backed by
Rust's [html5ever](https://github.com/servo/html5ever). Same HTML5 trees as
`BeautifulSoup(html, "html5lib")`, 6–14x faster.

```python
from bs4 import BeautifulSoup
import soup5ever

soup = BeautifulSoup(html, "html5ever")
```

## Installation

```
pip install soup5ever
```

Wheels for Linux (x86_64, aarch64; glibc and musl) and macOS (arm64), one `abi3` wheel per
platform for CPython 3.10+. The only dependency is `beautifulsoup4>=4.13`; no Rust, libxml2
or html5lib needed.

## Usage

Importing `soup5ever` registers the `"html5ever"` parser (also `"soup5ever"`). The generic
features `"html5"` and `"html"` are registered at the lowest priority, so importing it doesn't
change what `BeautifulSoup(markup, "html5")` or `BeautifulSoup(markup)` select.

The usual options work (`from_encoding`, `element_classes`, `multi_valued_attributes`,
`store_line_numbers`, `attribute_dict_class`). Like html5lib, `parse_only` isn't supported.

## Compatibility

The target is `BeautifulSoup(html, "html5lib")`; where html5lib and the HTML standard
disagree, soup5ever follows the standard.

- BS4's own tests for its html5lib builder: 93/93 pass.
- html5lib-tests tree construction: 1,588/1,592 match the spec. Against html5lib the trees
  are identical in 1,417 cases; the other 175 are classified automatically (167 html5lib
  behind the spec, 4 BS4 html5lib-adapter bugs, 4 `<selectedcontent>` misses both share).
- 182 hand-written differential cases and ~23k fuzz inputs (triaged with Chromium): every
  remaining difference is an html5lib bug or listed below.

Differences from html5lib:

- Current HTML standard where html5lib 1.1 (2020) is behind: the 2025 `<select>` rules,
  `<template>` in `<head>`, `</p>` in SVG/MathML, `<main>`/`<summary>`, `<search>`,
  `<dialog>`, ruby. See `tests/corpus.py` for each case.
- BS4's html5lib adapter never applies the Noah's Ark clause (`AttrList` has no `__eq__`);
  soup5ever does.
- Undeclared, valid UTF-8 bytes are decoded as UTF-8 (html5lib guesses windows-1252 without
  `chardet`). Decoding follows the WHATWG Encoding Standard, not Python's codecs.
- Lone surrogates in a `str` become U+FFFD.
- `sourceline`/`sourcepos` match html5lib for ~98.5% of elements.

Shared with html5lib: no `parse_only`, no `Script`/`Stylesheet` string subclasses, no
`<selectedcontent>` cloning.

## Benchmarks

`BeautifulSoup(markup, parser)` on an in-memory `str`, median of 7 rounds, 4-vCPU Linux VM,
CPython 3.11:

| document | html5lib | html5ever | speedup |
|---|---:|---:|---:|
| small page (3 KiB) | 2.4 ms | 250 µs | 9.6x |
| large page (1.2 MiB) | 888 ms | 101 ms | 8.8x |
| malformed tag soup | 483 ms | 34 ms | 14.2x |
| deeply nested | 243 ms | 26 ms | 9.3x |
| table-heavy | 507 ms | 69 ms | 7.3x |
| SVG/MathML-heavy | 323 ms | 51 ms | 6.4x |

Parsing in Rust is 14–32% of soup5ever's time; the rest is BeautifulSoup's own object
constructors. To reproduce:

```
pip install . html5lib
python benchmarks/run.py
```

## Development

```
python -m venv .venv && source .venv/bin/activate
pip install -U pip maturin
maturin develop --release -E dev
python scripts/fetch_html5lib_tests.py   # optional: html5lib-tests corpus
pytest
```

Lint with `ruff check . && ruff format --check .` and
`cargo fmt --check && cargo clippy --all-targets -- -D warnings`. Differential fuzzing is
separate: `python -m tests.fuzz --iterations 20000`.

## License

MIT
