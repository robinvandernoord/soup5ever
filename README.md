# soup5ever

A [BeautifulSoup 4](https://www.crummy.com/software/BeautifulSoup/) tree builder backed by
[html5ever](https://github.com/servo/html5ever), the HTML5 parser from Servo, written in Rust.

```python
from bs4 import BeautifulSoup
import soup5ever

soup = BeautifulSoup(html, "html5ever")
```

`BeautifulSoup(html, "html5lib")` is the reference: soup5ever aims to build the same tree,
out of the same ordinary `BeautifulSoup`, `Tag`, `NavigableString`, `Comment` and `Doctype`
objects, 6 to 14 times faster. Parsing and tree construction happen in Rust; what you get
back is a normal BeautifulSoup tree.

## Why

BeautifulSoup gives you three parsers. `html.parser` and `lxml` are fast but don't follow the
HTML5 parsing algorithm, so on malformed markup they build different trees than a browser
does. `html5lib` does follow it, but it is pure Python, and a large page can take a second to
parse. soup5ever keeps the HTML5 behavior and removes most of the cost.

## Installation

```
pip install soup5ever
```

Wheels are built for Linux (x86_64 and aarch64, glibc and musl), macOS (x86_64 and arm64)
and Windows (x64 and arm64). One `abi3` wheel per platform covers CPython 3.10 and newer. The
only runtime dependency is `beautifulsoup4` (4.13 or newer). You don't need Rust, libxml2,
or html5lib to install or use it.

## Usage

Import `soup5ever` once, anywhere, then ask BeautifulSoup for `"html5ever"`:

```python
from bs4 import BeautifulSoup
import soup5ever

soup = BeautifulSoup("<p>Hello <b>world", "html5ever")
soup.p.b.string  # 'world'
soup.p.sourceline  # 1
```

Byte input is decoded the way a browser (and html5lib) would: a BOM, then `from_encoding`,
then a `<meta charset>` in the first 1024 bytes, then a late `<meta charset>` found while
parsing (which re-parses the document).

```python
soup = BeautifulSoup(open("page.html", "rb"), "html5ever")
soup.original_encoding  # e.g. 'windows-1252', 'utf-8', 'shift_jis'
```

The usual BeautifulSoup options work: `from_encoding`, `element_classes`,
`multi_valued_attributes`, `store_line_numbers`, a custom `attribute_dict_class`, `builder=`.
As with html5lib, `parse_only` is not supported. You get a warning and the whole document is
parsed.

### Parser registration

Importing `soup5ever` registers `soup5ever.HTML5everTreeBuilder` with BeautifulSoup's
builder registry under the feature names `"html5ever"` and `"soup5ever"`. BeautifulSoup has
no plugin mechanism, so the import is what registers it.

The builder also advertises the generic features `"html5"`, `"html"` and `"permissive"`, but
it registers them at the lowest priority. Importing soup5ever therefore doesn't change what
`BeautifulSoup(markup, "html5")` or `BeautifulSoup(markup)` select. If html5lib is installed,
`"html5"` still means html5lib, and soup5ever answers to generic names only when nothing else
does. You can also pass the class: `BeautifulSoup(markup, builder=HTML5everTreeBuilder)`.

## Compatibility

`BeautifulSoup(markup, "html5lib")` is the behavioral target, and HTML5 semantics win where
the two conflict. html5lib-python's last release (1.1) is from 2020, and the HTML standard
has changed since then. Current status:

- **BeautifulSoup's own builder tests.** soup5ever passes the test class BeautifulSoup runs
  against its html5lib builder (`HTML5TreeBuilderSmokeTest`, on top of
  `HTMLTreeBuilderSmokeTest`, plus the html5lib-specific tests): 93 of 93. These tests are
  taken from the BS4 sdist, so CI runs each supported BS4 release (4.13.1, 4.14.3, latest)
  against its own tests.
- **html5lib-tests tree construction (spec).** Of 1,592 applicable cases (whole documents,
  scripting off), soup5ever's BeautifulSoup tree matches the expected tree in 1,588. The four
  misses are `<selectedcontent>` cloning; see below.
- **The same corpus, against html5lib.** The trees are identical in 1,417 cases. In the other
  175, every difference is accounted for automatically:
  - 167 where html5lib-python's parser differs from the spec and soup5ever doesn't;
  - 4 where BS4's html5lib adapter breaks html5lib (native html5lib and soup5ever both match
    the spec);
  - 4 where soup5ever misses the spec (`<selectedcontent>`; html5lib misses those too).
- **Differential corpus.** 182 hand-written cases, grouped by trouble spot (implied
  elements, adoption agency, tables and foster parenting, SVG/MathML, comments, doctypes,
  entities, NULs, attributes, raw text, templates, and so on), plus larger generated
  documents. Each is compared structurally: node types, names, namespaces, prefixes,
  attributes including `NamespacedAttribute` details, text and child order. The
  `next_element`/`previous_element` chains are compared node by node as well. Every
  difference is listed and classified in [`tests/corpus.py`](tests/corpus.py).
- **Real-world pages.** On 317 HTML files found on a development machine (language
  documentation, generated reports, license pages), the trees were identical for 297.
  Eighteen of the rest were undeclared UTF-8, which html5lib decoded as windows-1252
  (see below). The other two put a `<template>` in `<head>`, where html5lib is wrong.
- **Fuzzing.** A seeded generator/mutator targets the trouble spots, and mismatches are
  auto-minimized and triaged with Chromium's parser as an independent oracle. In 10,000
  inputs it found 47 distinct mismatches, all of them html5lib bugs. It also found one
  html5ever bug, which soup5ever works around (below).

So compatibility is high but not perfect, and the differences are known and listed.

### Known differences from html5lib

soup5ever follows the current HTML standard where html5lib-python 1.1 does not. Each of these
was checked against the html5lib-tests expectations or against Chromium:

- The 2025 `<select>` changes: `<select>` keeps elements such as `<div>`, `<b>`, `<svg>` or
  `<button>` that html5lib drops.
- A leading `<template>` goes in `<head>`, not `<body>`. Other template-mode rules also
  follow the spec.
- `</p>` and `</br>` break out of SVG/MathML.
- `<main>` and `<summary>` are "special" elements for the adoption agency algorithm.
- `<search>` and `<dialog>` close an open `<p>`.
- The `<rb>`/`<rtc>` ruby rules apply.
- `<isindex>`, `<menuitem>` and `<keygen>` are handled as they are today.
- Recent adoption agency refinements are included.
- Several newline and foster-parenting edge cases differ: a `<textarea>` inside a
  `<table>`, a LF after `<listing>` that isn't the next token, and an end tag inside a
  `<template>`.

soup5ever doesn't reproduce these bugs in BS4's html5lib adapter:

- **Noah's Ark clause.** html5lib compares `node.attributes` to decide whether two
  formatting elements match. The adapter returns a new `AttrList` (which has no `__eq__`)
  on every access, so the clause never fires, and something like `<p><b><b><b><b><p>x`
  reconstructs four `<b>`s instead of three.

These differences are intentional:

- **Undeclared UTF-8 is decoded as UTF-8.** Without a BOM, `from_encoding` or `<meta charset>`,
  byte input that is valid, non-ASCII UTF-8 is treated as UTF-8. html5lib guesses
  windows-1252 unless `chardet` is installed, which produces mojibake for most such pages.
  Everything else falls back to windows-1252, as in html5lib.
- **WHATWG decoders.** Decoding uses [encoding_rs](https://github.com/hsivonen/encoding_rs),
  which follows the WHATWG Encoding Standard exactly. html5lib uses Python's codecs, which
  differ in places: windows-1252 bytes 0x81, 0x8D, 0x8F, 0x90 and 0x9D decode to C1
  controls rather than U+FFFD, and Shift_JIS, EUC-KR and similar encodings cover the WHATWG
  superset. `original_encoding` uses the same names html5lib reports.
- **`from_encoding` also accepts Python codec names** (e.g. `"latin-1"`) when they aren't
  WHATWG labels. html5lib silently ignores those.
- **Lone surrogates in a `str` become U+FFFD.** Rust strings can't hold them; html5lib passes
  them through.

soup5ever shares these limitations with html5lib:

- `<selectedcontent>` cloning (from the 2025 select changes) isn't done. html5ever only
  attempts it on an explicit `</option>` (servo/html5ever#712), and it is DOM mutation that
  BeautifulSoup has no use for.
- No `parse_only`. Strings inside `<script>`, `<style>` and `<template>` are plain
  `NavigableString`s. There is no fragment parsing.

Source positions (`sourceline`, `sourcepos`) follow html5lib's definition: the stream
position when the element was created, which for a start tag is the column of its `>`.
Adoption-agency copies of formatting elements get no position, as in html5lib. For trees
that are otherwise identical, positions agree on 98.5% of the html5lib-tests corpus. The
rest are off by a few columns around character references and raw-text end tags, where
html5lib reads ahead differently.

html5ever parse errors are discarded before they reach the tree builder. Besides saving time,
this works around an html5ever bug where a parse error between `<pre>` or `<listing>` and a
following newline made it keep the newline that the spec says to drop.

## Benchmarks

What is timed is `BeautifulSoup(markup, parser)` on a `str` already in memory, for
`"html5lib"` and `"html5ever"`. No file I/O, imports or interpreter start-up is included.
Each measurement is one warm-up call followed by 7 rounds sized to about 6 s in total; the
table shows the median time per call (the JSON output also has minimums). The garbage
collector stays on, as in real use, and is run between rounds. The documents are generated
deterministically by [`benchmarks/documents.py`](benchmarks/documents.py), and the two
parsers build equivalent trees for all of them.

Measured on a 4-vCPU Intel Xeon (2.1 GHz) Linux VM, CPython 3.11.15, beautifulsoup4 4.15.0, html5lib 1.1, soup5ever 0.1.0 (release build, abi3). The VM is shared, so expect ±10% run to run.

| document | size | nodes | html5lib | html5ever | speedup | soup5ever: Rust parse | html5lib: parser only |
|---|---:|---:|---:|---:|---:|---:|---:|
| small normal page | 3 KiB | 112 | 2.4 ms | 250 µs | **9.6x** | 57 µs (23%) | 1.3 ms (54%) |
| large normal page | 1226 KiB | 40,588 | 888.0 ms | 101.2 ms | **8.8x** | 22.1 ms (22%) | 374.2 ms (42%) |
| malformed tag soup | 104 KiB | 10,516 | 483.4 ms | 34.1 ms | **14.2x** | 10.7 ms (31%) | 190.6 ms (39%) |
| deeply nested (depth 500) | 70 KiB | 6,009 | 243.4 ms | 26.1 ms | **9.3x** | 8.5 ms (32%) | 101.3 ms (42%) |
| table-heavy (1500x8) | 301 KiB | 27,059 | 506.6 ms | 69.0 ms | **7.3x** | 9.6 ms (14%) | 276.1 ms (54%) |
| SVG/MathML-heavy | 246 KiB | 14,151 | 322.9 ms | 50.8 ms | **6.4x** | 8.3 ms (16%) | 191.9 ms (59%) |

On the 317 real-world files mentioned above, parsing all of them took 0.84 s with soup5ever and 10.5 s with html5lib (12.5x).

The last two columns break the time down. For soup5ever, "Rust parse" is decoding,
tokenizing and tree construction with no Python objects created, so the remainder is
BeautifulSoup object construction: calling `Tag.__init__`, `NavigableString.__new__` and
BS4's multi-valued-attribute processing, as every builder must. For html5lib, "parser only"
is html5lib with its native `etree` tree builder, so the remainder is BS4's html5lib adapter.

Parsing is no longer the bottleneck. Most of soup5ever's time is spent inside BeautifulSoup's
own constructors, and the remaining speedup comes from building each object exactly once, in
its final place, with no reparenting on Python objects. Documents nested thousands of levels
deep are quadratic in both parsers, because the spec's "has an element in scope" check walks
the stack of open elements; soup5ever is about 18x faster there.

Run them yourself:

```
pip install html5lib
python -m benchmarks.run            # or --quick
```

## How it works

1. **Decode** (byte input only): BOM, `from_encoding`, the WHATWG `<meta>` prescan, then the
   UTF-8 check, then windows-1252 (`src/encoding.rs`).
2. **Parse** with html5ever into an arena tree in Rust, with the GIL released
   (`src/sink.rs`, `src/driver.rs`). html5ever's `TreeSink` rearranges the tree as it parses
   (foster parenting, the adoption agency algorithm, `reparent_children`, text merging).
   With `u32` node ids and intrusive child lists, every one of those operations is O(1) and
   none of them touches Python. If a `<meta charset>` shows up while the encoding is still
   tentative, parsing stops and restarts with the new encoding.
3. **Convert** the finished tree to BeautifulSoup objects in one pre-order pass
   (`src/convert.rs`). Each node is created through the soup's element classes, the same
   way `BeautifulSoup.new_tag` and html5lib's adapter create them. Then `parent`, the
   sibling and element pointers, and `contents` are set directly. Because the tree is
   final, each object is created and linked exactly once, so the navigation pointers are
   correct by construction. html5lib's adapter has to repair them after moving nodes.

The design follows from html5lib's approach: its adapter mirrors every tree-builder
operation onto Python objects, including all the reparenting. Implementing html5ever's
`TreeSink` directly on Python objects would cross the Rust/Python boundary for every tree
mutation and inherit the same repair work. The intermediate Rust tree keeps parsing entirely
in Rust and crosses the boundary once per parse.

To match html5lib's source positions without html5ever exposing columns, the input is fed
to the tokenizer in chunks that end after each `>` and before each `<`, `&` and NUL. Tokens
are emitted at chunk ends, so each element's position is known when it is created. The
chunks are sub-slices of one buffer, and the tree is the same whether or not positions are
tracked (a property test checks this). Tracking costs about 6% of the total time;
`store_line_numbers=False` turns it off. The cyclic garbage collector is paused while the
tree is built, because the new objects all stay reachable. That is 25–30% faster on large
documents, and a collector you turned off stays off.

The Python surface is `soup5ever.HTML5everTreeBuilder` and `soup5ever.register()`.

## Development

```
git clone https://github.com/robinvandernoord/soup5ever
cd soup5ever

python -m venv .venv
source .venv/bin/activate

pip install -U pip maturin
maturin develop --release -E dev     # builds the extension; installs pytest, html5lib, hypothesis, ruff
python scripts/fetch_html5lib_tests.py   # optional: the html5lib-tests corpus

pytest
```

Re-run `maturin develop --release` after changing Rust code. Python changes take effect
immediately.

You need a Rust toolchain (stable) to build from source. The Rust code is only reachable
through the Python package; it isn't published as a crate.

Formatting and linting use the standard tools:

```
ruff check . && ruff format --check .
cargo fmt --check && cargo clippy --all-targets -- -D warnings
cargo test --release
```

## Testing

`pytest` runs everything below except fuzzing, in about 10 seconds:

- `tests/test_bs4_smoke.py`: BeautifulSoup's own tree-builder tests, vendored from the BS4
  sdist by `scripts/sync_bs4_tests.py` (run it to re-sync for the installed BS4 version).
- `tests/test_html5lib_tests.py`: the html5lib-tests tree-construction corpus, as a spec
  check and as a differential check where every disagreement must be explained. Download
  it first with `python scripts/fetch_html5lib_tests.py`; without it these tests are
  skipped. The corpus is pinned to the last commit before upstream moved it to
  web-platform-tests.
- `tests/test_differential.py`: the classified differential corpus and generated
  documents, compared against html5lib.
- `tests/test_builder.py`: registration, encodings, positions, object types, and regression
  tests for every compatibility bug found during development.
- `tests/test_properties.py`: Hypothesis property tests that need no reference parser:
  consistent linkage, tree independence from position tracking, str/bytes agreement, and
  arbitrary bytes.

Fuzzing is separate:

```
python -m tests.fuzz --iterations 20000 --seed 7
```

The fuzzer minimizes and saves each mismatch under `tests/fuzz_failures/`. If Node.js,
Playwright and Chromium are available, it triages each mismatch with Chromium's parser
(`tests/oracle/`) and exits non-zero only for mismatches it can't attribute to html5lib.
Turn real findings into cases in `tests/corpus.py`.

## License

MIT
