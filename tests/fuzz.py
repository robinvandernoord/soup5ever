"""Differential fuzzing: html5ever vs html5lib on generated and mutated HTML.

    python -m tests.fuzz --iterations 20000 --seed 1

Every input is derived from ``(seed, iteration)``, so a failure is
reproducible from the two numbers printed with it. Mismatches are minimized
(tests/minimize.py), de-duplicated and saved under tests/fuzz_failures/.

The first oracle is BeautifulSoup's html5lib builder with its Noah's Ark
adapter bug fixed (`canon.html5lib_adapter_fixed`). html5lib-python 1.1 is
behind the HTML standard in many places, so the generator avoids the areas
listed in `AVOIDED`, and every remaining mismatch is triaged with Chromium's
parser (tests/oracle) when Node.js/Playwright/Chromium are available: only
mismatches where Chromium does *not* side with soup5ever count as soup5ever
bugs, and make the command exit non-zero. Without Chromium, every mismatch
is reported for manual triage.

Fuzzing is not part of the normal test run.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import random
import warnings

from bs4 import BeautifulSoup

import soup5ever  # noqa: F401

from . import canon
from .corpus import CASES, KNOWN_DIFFERENCES
from .minimize import minimize

FAILURES = pathlib.Path(__file__).parent / "fuzz_failures"

#: Areas where html5lib-python 1.1 is known to be behind the HTML standard
#: (tests/test_html5lib_tests.py verifies each of these against the spec
#: corpus). Generated input stays out of them so mismatches mean bugs.
AVOIDED = (
    "select (2025 content model changes)",
    "ruby rb/rtc", "search", "dialog", "menuitem", "isindex", "keygen",
    "template before <body> (html5lib puts it in <body>)",
)

FORMATTING = ["a", "b", "big", "code", "em", "font", "i", "nobr", "s", "small",
              "strike", "strong", "tt", "u"]
BLOCK = ["div", "p", "section", "article", "aside", "nav", "header", "footer",
         "blockquote", "address", "center", "h1", "h2", "pre", "listing", "ul",
         "ol", "li", "dl", "dt", "dd", "form", "fieldset", "figure", "main",
         "details", "summary", "button"]
TABLE = ["table", "caption", "colgroup", "col", "thead", "tbody", "tfoot", "tr",
         "td", "th"]
RAW = ["script", "style", "textarea", "title", "xmp", "iframe", "noembed",
       "noframes", "noscript", "plaintext"]
VOID = ["br", "hr", "img", "input", "wbr", "area", "embed", "param", "source",
        "track", "image", "meta", "link", "base"]
SVG = ["svg", "g", "path", "circle", "foreignObject", "foreignobject", "desc",
       "title", "clipPath", "lineargradient", "text", "font", "use"]
MATH = ["math", "mi", "mo", "mn", "ms", "mtext", "mglyph", "malignmark",
        "annotation-xml", "mrow"]
OTHER = ["span", "label", "option", "optgroup", "template", "html", "head",
         "body", "frameset", "frame", "object", "applet", "marquee", "my-el",
         "applet", "math", "svg", "table", "p", "a"]
ATTRS = ["id", "class", "href", "style", "title", "xlink:href", "xml:lang",
         "xmlns", "xmlns:xlink", "viewbox", "definitionurl", "encoding", "type",
         "color", "size", "face", "a", "B", "data-x", "☃", "x<y", "\"q"]
VALUES = ["", "x", "a b  c", "text/html", "hidden", "red", "1", "&amp;",
          "&lt;&copy", "\x00", "<b>", "'", '"', "é\U0001F600", "application/xhtml+xml"]
TEXT = ["x", "hello world", " ", "\n", "\t", "\r\n", "\x00", "&amp;", "&copy",
        "&notin;", "&#x110000;", "&#0;", "&#128;", "&", "<", ">", "&#x0D;",
        " ", "\U0001F600", "]]>", "<![CDATA[x]]>", "--"]
MISC = ["<!-- c -->", "<!---->", "<!-->", "<!-- a -- b --!>", "<!", "<?pi x?>",
        "</>", "</ x>", "<!DOCTYPE html>", '<!DOCTYPE html PUBLIC "a" "b">',
        "<!doctype>", "<![CDATA[c]]>", "</p>", "</br>", "<", "<3", "</#x>"]


def _attrs(rng: random.Random) -> str:
    out = []
    for _ in range(rng.choice([0, 0, 0, 1, 1, 2, 3])):
        name = rng.choice(ATTRS)
        value = rng.choice(VALUES)
        quote = rng.choice(['"', "'", ""])
        if not quote and any(c in value for c in " \"'=<>`"):
            quote = '"'
        if quote and quote in value:
            quote = "'" if quote == '"' else '"'
        if quote in value:
            out.append(f" {name}")
        else:
            out.append(f" {name}={quote}{value}{quote}" if value or quote else f" {name}")
    return "".join(out)


def token(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.18:
        return rng.choice(TEXT)
    if r < 0.25:
        return rng.choice(MISC)
    group = rng.choice([FORMATTING, FORMATTING, BLOCK, TABLE, TABLE, RAW, VOID, SVG, MATH, OTHER])
    name = rng.choice(group)
    if name in ("select",):
        name = "span"
    kind = rng.random()
    if kind < 0.35:
        return f"</{name}>"
    self_closing = "/" if rng.random() < 0.1 else ""
    tag = f"<{name}{_attrs(rng)}{self_closing}>"
    if name in RAW and rng.random() < 0.7:
        tag += rng.choice(TEXT + ["<b>", "</p>", "<!--", "-->", "<script>"]) + f"</{name}>"
    return tag


def generate(rng: random.Random) -> str:
    # Start in <body> so a <template> can't end up before it.
    return "<body>" + "".join(token(rng) for _ in range(rng.randint(1, 40)))


def mutate(rng: random.Random, markup: str) -> str:
    for _ in range(rng.randint(1, 4)):
        op = rng.random()
        pos = rng.randint(0, len(markup))
        if op < 0.4:
            markup = markup[:pos] + token(rng) + markup[pos:]
        elif op < 0.6 and markup:
            end = min(len(markup), pos + rng.randint(1, 8))
            markup = markup[:pos] + markup[end:]
        elif op < 0.75:
            markup = markup[:pos]  # unexpected EOF
        elif op < 0.9 and markup:
            start = rng.randint(0, len(markup) - 1)
            piece = markup[start:start + rng.randint(1, 30)]
            markup = markup[:pos] + piece + markup[pos:]
        else:
            markup = markup[:pos] + rng.choice("<>&\"'=/\x00\r\n!-") + markup[pos:]
    return markup


SEEDS = [CASES[k] for k in sorted(CASES) if k not in KNOWN_DIFFERENCES
         and "select" not in CASES[k] and "template" not in CASES[k]
         and "ruby" not in CASES[k]]


def input_for(seed: int, iteration: int) -> str:
    rng = random.Random(f"{seed}:{iteration}")
    if rng.random() < 0.6:
        return generate(rng)
    return "<body>" + mutate(rng, rng.choice(SEEDS))


def _avoided(markup: str) -> bool:
    lowered = markup.lower()
    return any(
        f"<{name}" in lowered
        for name in ("select", "ruby", "rb", "rtc", "search", "dialog", "menuitem", "isindex", "keygen")
    )


def check(markup: str) -> str | None:
    """None if the builders agree, else a description of the difference."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ours = BeautifulSoup(markup, "html5ever")
        with canon.html5lib_adapter_fixed():
            theirs = BeautifulSoup(markup, "html5lib")
    problems = canon.linkage_problems(ours)
    if problems:
        return f"linkage: {problems[0]}"
    return canon.diff(canon.canonical(ours), canon.canonical(theirs))


def run(seed: int, iterations: int, save: bool = True) -> list[tuple[int, str, str]]:
    failures = []
    for i in range(iterations):
        markup = input_for(seed, i)
        if _avoided(markup):
            continue
        difference = check(markup)
        if difference is None:
            continue
        small = minimize(markup, lambda m: check(m) is not None and not _avoided(m))
        failures.append((i, small, check(small)))
        if save:
            FAILURES.mkdir(exist_ok=True)
            name = hashlib.sha1(small.encode("utf-8", "surrogatepass")).hexdigest()[:12]
            (FAILURES / f"{name}.html").write_text(small, encoding="utf-8")
    return failures


def triage(inputs: list[str]) -> list[str] | None:
    """Chromium's verdict for each input, or None if Chromium isn't available."""
    try:
        from .oracle.classify import chromium, trees

        results = chromium(inputs)
    except Exception as exc:  # noqa: BLE001 - optional tooling
        print(f"(Chromium oracle unavailable: {exc.__class__.__name__}; not triaging)")
        return None
    verdicts = []
    for markup, browser in zip(inputs, results):
        ours, theirs = trees(markup)
        if ours == browser:
            verdicts.append("html5lib bug")
        elif theirs == browser:
            verdicts.append("SOUP5EVER BUG")
        else:
            verdicts.append("unclear (all differ)")
    return verdicts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-triage", action="store_true")
    args = parser.parse_args()
    failures = run(args.seed, args.iterations, save=not args.no_save)
    distinct: dict[str, tuple[int, str]] = {}
    for i, small, difference in failures:
        distinct.setdefault(small, (i, difference))
    verdicts = None if args.no_triage or not distinct else triage(list(distinct))
    bugs = 0
    for n, (small, (i, difference)) in enumerate(distinct.items()):
        verdict = verdicts[n] if verdicts else "untriaged"
        bugs += verdict != "html5lib bug"
        print(f"[{verdict}] seed={args.seed} iteration={i}: {small!r}\n    {difference}")
    print(f"{args.iterations} inputs, {len(failures)} mismatches, {len(distinct)} distinct, "
          f"{bugs} not attributable to html5lib")
    raise SystemExit(1 if bugs else 0)


if __name__ == "__main__":
    main()
