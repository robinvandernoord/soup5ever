"""Deterministic benchmark (and test) documents.

Generated rather than downloaded, so the benchmark is reproducible and the
repository carries no third-party content. Each generator takes a `scale`
and returns `str`; the same seed always gives the same document.
"""

from __future__ import annotations

import random

WORDS = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua enim ad minim veniam quis nostrud "
    "exercitation ullamco laboris nisi aliquip ex ea commodo consequat duis aute irure "
    "reprehenderit voluptate velit esse cillum fugiat nulla pariatur excepteur sint "
    "occaecat cupidatat non proident sunt culpa qui officia deserunt mollit anim id est"
).split()


def _words(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n))


def _inline(rng: random.Random, n: int) -> str:
    out = []
    for _ in range(n):
        r = rng.random()
        w = _words(rng, rng.randint(2, 8))
        if r < 0.15:
            out.append(f'<a href="/page/{rng.randint(1, 999)}" class="link">{w}</a>')
        elif r < 0.25:
            out.append(f"<strong>{w}</strong>")
        elif r < 0.32:
            out.append(f"<em>{w}</em>")
        elif r < 0.36:
            out.append(f"<code>{w}</code>")
        elif r < 0.38:
            out.append("&amp; &copy; &mdash; &#8217;")
        else:
            out.append(w)
    return " ".join(out)


def _head(title: str) -> str:
    return (
        "<!DOCTYPE html>\n<html lang=en>\n<head>\n<meta charset=utf-8>\n"
        f"<title>{title}</title>\n"
        '<meta name=viewport content="width=device-width, initial-scale=1">\n'
        '<link rel=stylesheet href="/static/site.css">\n'
        "<style>body { font: 16px/1.5 sans-serif } .nav > li { display: inline }</style>\n"
        "<script>window.dataLayer = window.dataLayer || []; if (a < b && c > d) {}</script>\n"
        "</head>\n"
    )


def normal(scale: int = 1, seed: int = 1) -> str:
    """A content page: header, navigation, articles, sidebar, footer."""
    rng = random.Random(seed)
    parts = [
        _head("Normal page"),
        "<body class='page home'>\n<header id=top>\n<nav>\n<ul class=nav>",
    ]
    for i in range(8):
        parts.append(f'<li><a href="/section/{i}">{_words(rng, 2)}</a></li>')
    parts.append("</ul>\n</nav>\n</header>\n<main>\n")
    for a in range(10 * scale):
        parts.append(f'<article id="post-{a}" class="post entry">\n<h2>{_words(rng, 6)}</h2>\n')
        parts.append(
            f'<p class=meta>Posted <time datetime="2026-01-{a % 28 + 1:02d}">today</time></p>\n'
        )
        for _ in range(rng.randint(3, 6)):
            parts.append(f"<p>{_inline(rng, rng.randint(8, 20))}</p>\n")
        if rng.random() < 0.4:
            parts.append(
                "<ul>" + "".join(f"<li>{_inline(rng, 3)}</li>" for _ in range(5)) + "</ul>\n"
            )
        if rng.random() < 0.3:
            parts.append(
                f'<figure><img src="/img/{a}.jpg" alt="{_words(rng, 3)}" width=640 height=480>'
                f"<figcaption>{_words(rng, 5)}</figcaption></figure>\n"
            )
        parts.append("</article>\n")
    parts.append("</main>\n<aside><h3>Links</h3><ul>")
    for _ in range(20):
        parts.append(
            f'<li><a href="https://example.com/{rng.randint(1, 10**6)}">{_words(rng, 3)}</a>'
        )
    parts.append(
        "</ul></aside>\n<footer><p>&copy; 2026 Example</p>"
        "<form action=/subscribe method=post><input type=email name=email>"
        "<button type=submit>Subscribe</button></form></footer>\n</body>\n</html>\n"
    )
    return "".join(parts)


def small(seed: int = 1) -> str:
    """A small but complete page (a few KB)."""
    rng = random.Random(seed)
    return (
        _head("Small page")
        + "<body><h1>Hello</h1>"
        + "".join(f"<p>{_inline(rng, 10)}</p>" for _ in range(6))
        + "<ul>"
        + "".join(f"<li><a href='/{i}'>{_words(rng, 2)}</a></li>" for i in range(6))
        + "</ul>"
        + "</body></html>"
    )


def malformed(scale: int = 1, seed: int = 2) -> str:
    """Tag soup: unclosed and misnested elements, stray end tags, broken tables."""
    rng = random.Random(seed)
    parts = ["<html><title>soup</title><body bgcolor=white>"]
    fragments = [
        lambda: f"<p>{_words(rng, 5)}<p>{_words(rng, 5)}",
        lambda: f"<b>{_words(rng, 3)}<i>{_words(rng, 3)}</b>{_words(rng, 3)}</i>",
        lambda: f"<font color=red><center>{_words(rng, 4)}</font></center>",
        lambda: f"<table><tr><td>{_words(rng, 2)}<td>{_words(rng, 2)}<tr>{_words(rng, 2)}</table>",
        lambda: f"<a href=x>{_words(rng, 2)}<div>{_words(rng, 3)}</a></div>",
        lambda: f"<ul><li>{_words(rng, 2)}<li>{_words(rng, 2)}<ul><li>{_words(rng, 2)}</ul>",
        lambda: f"</span></div>{_words(rng, 3)}</p></b>",
        # Markup inside an attribute value. (Kept terminated: an unterminated
        # quote swallows whatever follows, which randomly leaves a <select>
        # open around later markup, where html5lib predates the 2025 select
        # parsing rules; see tests/corpus.py "select-formatting".)
        lambda: f'<div class="x>{_words(rng, 2)}</div><b>">{_words(rng, 2)}</div>',
        lambda: f"<select><option>{_words(rng, 1)}<option>{_words(rng, 1)}</select>",
        # (Three, not four: four identical open <b>s hit BS4's html5lib
        # adapter bug in the Noah's Ark clause; see tests/corpus.py.)
        lambda: f"<p><b><b><b>{_words(rng, 2)}</b></b><p>{_words(rng, 2)}",
        lambda: f"<h1>{_words(rng, 2)}<h2>{_words(rng, 2)}</h1>",
        lambda: "<form><table><form><tr><td><input name=q></form></table>",
        lambda: f"&amp &lt &copy {_words(rng, 2)} &#x2603 &bogus;",
        lambda: f"<!-- {_words(rng, 3)} -- -->",
        lambda: f"<br/></br><hr><img src=a alt={_words(rng, 1)}>",
    ]
    for _ in range(400 * scale):
        parts.append(rng.choice(fragments)())
        parts.append("\n")
    return "".join(parts)


def deep(depth: int = 500, repeat: int = 4) -> str:
    """Deeply nested block and inline elements."""
    unit = "".join(f"<div class=d{i % 7}><span>{i}</span>" for i in range(depth)) + "x"
    unit += "</div>" * depth
    return "<!DOCTYPE html><body>" + unit * repeat


def tables(rows: int = 1500, cols: int = 8, seed: int = 3) -> str:
    """A large data table, with implied tbody/tr/td structure and some foster parenting."""
    rng = random.Random(seed)
    parts = [
        "<!DOCTYPE html><title>report</title><table class=data><caption>Report</caption>",
        "<thead><tr>"
        + "".join(f"<th scope=col>{_words(rng, 1)}" for _ in range(cols))
        + "</thead>",
    ]
    for r in range(rows):
        parts.append(f"<tr class={'odd' if r % 2 else 'even'}>")
        for c in range(cols):
            if c == 0:
                parts.append(f"<td><a href='/row/{r}'>{r}</a>")
            else:
                parts.append(f"<td align=right>{rng.randint(0, 10**6):,}")
        if r % 100 == 50:
            parts.append("stray text <b>fostered</b>")
    parts.append("</table>")
    return "".join(parts)


def foreign(scale: int = 1, seed: int = 4) -> str:
    """A page with lots of inline SVG and MathML."""
    rng = random.Random(seed)
    parts = [_head("Foreign content"), "<body>"]
    for i in range(60 * scale):
        parts.append(f"<p>{_inline(rng, 6)}</p>")
        parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewbox="0 0 100 100" width=24 height=24><defs><lineargradient id=g{i}>'
            f"<stop offset=0 stop-color=red /></lineargradient><clippath id=c{i}><rect width=10 "
            f'height=10 /></clippath></defs><g clip-path="url(#c{i})"><circle cx=50 cy=50 r=40 '
            f'fill="url(#g{i})"/><path d="M10 10 L90 90 Z" /><use xlink:href="#g{i}" />'
            f"<foreignObject><p>html in svg</p></foreignObject><text>{_words(rng, 2)}</text></g></svg>"
        )
        parts.append(
            "<math display=block><mrow><mi>x</mi><mo>=</mo><mfrac><mrow><mo>-</mo><mi>b</mi>"
            "<mo>&PlusMinus;</mo><msqrt><msup><mi>b</mi><mn>2</mn></msup><mo>-</mo><mn>4</mn>"
            "<mi>a</mi><mi>c</mi></msqrt></mrow><mrow><mn>2</mn><mi>a</mi></mrow></mfrac></mrow>"
            "<annotation-xml encoding='text/html'><b>formula</b></annotation-xml></math>"
        )
    parts.append("</body></html>")
    return "".join(parts)


#: name -> (description, zero-argument factory)
BENCHMARKS = {
    "small": ("small normal page", lambda: small()),
    "large": ("large normal page", lambda: normal(scale=40)),
    "malformed": ("malformed tag soup", lambda: malformed(scale=5)),
    "deep": ("deeply nested (depth 500)", lambda: deep(500, 4)),
    "tables": ("table-heavy (1500x8)", lambda: tables(1500, 8)),
    "foreign": ("SVG/MathML-heavy", lambda: foreign(scale=4)),
}

#: Smaller variants of every kind, for the differential tests.
TEST_DOCUMENTS = {
    "small": lambda: small(),
    "normal": lambda: normal(scale=2),
    "malformed": lambda: malformed(scale=1),
    "deep": lambda: deep(200, 1),
    "tables": lambda: tables(120, 5),
    "foreign": lambda: foreign(scale=1),
}
