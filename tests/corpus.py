"""Hand-written differential corpus, grouped by HTML5 trouble spot.

Every entry is parsed with both ``html5lib`` and ``html5ever`` and the
canonical trees compared (see test_differential.py). Entries whose trees are
*expected* to differ are listed in `KNOWN_DIFFERENCES` with a
classification; everything else must match exactly.
"""

from __future__ import annotations

CASES: dict[str, str] = {
    # --- implied structure -------------------------------------------------
    "empty": "",
    "whitespace-only": " \n\t ",
    "text-only": "Hello, world",
    "bare-p": "<p>Hello</p>",
    "head-content-only": "<title>x</title><meta charset=utf-8><link rel=x>",
    "body-content-in-head": "<head><p>x</p></head><body>y",
    "double-head": "<html><head><title>a</title></head><head><title>b</title></head>",
    "double-body": "<body a=1><p>x<body b=2 a=3>y",
    "double-html": "<html lang=en><p>x<html dir=rtl lang=fr>",
    "after-body-content": "<html><body></body></html><p>late</p><!--c-->",
    "after-html-comment": "<html></html><!-- after -->",
    "whitespace-before-head": "<html>  \n <head> </head> \n<body> </body> \n</html> \n",
    # --- unclosed / misnested ---------------------------------------------
    "unclosed-p": "<p>one<p>two<div>three",
    "unclosed-li": "<ul><li>a<li>b<ul><li>c</ul><li>d</ul>",
    "unclosed-dt-dd": "<dl><dt>a<dd>b<dt>c<dd>d</dl>",
    "unclosed-option": "<select><option>a<option>b<optgroup><option>c</select>",
    "stray-end-tags": "</div></p></span>text</b></i>",
    "end-br": "a</br>b</p>c",
    "p-in-button": "<button><p>x</button>y",
    "heading-in-heading": "<h1>a<h2>b</h1>c",
    "nested-forms": "<form id=a><form id=b><input></form></form>",
    "nested-a": "<a href=1>x<a href=2>y</a>z",
    "nested-nobr": "<nobr>a<nobr>b</nobr>c",
    "li-in-li-in-div": "<li>a<div><li>b</div>",
    "unclosed-at-eof": "<div><span><b>eof",
    # --- adoption agency / formatting --------------------------------------
    "aaa-basic": "<p><b>bold<i>both</b>italic</i></p>",
    "aaa-block": "<b>1<p>2</b>3</p>",
    "aaa-div": "<a>1<div>2<div>3</a>4</div>5</div>",
    "aaa-reparented": "<p><em>foo</p>\n<p>bar<a></a></em></p>",
    "aaa-many-formatting": "<b><i><u><s><em><strong>x<p>y</b>z",
    "noahs-ark": "<p><b><b><b><b>x</b></b></b></b>" "<p><b class=a><b class=a><b class=a><b class=a>y",
    "noahs-ark-attrs": "<b a=1><b a=1><b a=2><b a=1><b a=1><p>x",
    "formatting-across-table": "<b><table><td>x</b>y</table>z",
    "formatting-reconstruct": "<i>a<p>b<p>c</i>d",
    "font-color": "<font color=red><p>x</font>y",
    "aaa-outer-loop-limit": "<a>" + "<div>" * 12 + "</a>",
    # --- tables ------------------------------------------------------------
    "table-implied-tbody": "<table><tr><td>1<td>2<tr><td>3</table>",
    "table-thead-tfoot": "<table><thead><tr><th>h<tfoot><tr><td>f<tbody><tr><td>b</table>",
    "table-caption-colgroup": "<table><caption>c<col><colgroup><col span=2><tr><td>x</table>",
    "table-nested": "<table><tr><td><table><tr><td>inner</table>outer</table>",
    "table-foster-text": "<table>foo<tr>bar<td>baz</td>qux</tr>quux</table>",
    "table-foster-elements": "<table><div>a</div><tr><td>b</td></tr><span>c</span></table>",
    "table-foster-whitespace": "<table> <tr> <td>x</td> </tr> </table>",
    "table-foster-comment": "<table><!--c--><tr><!--d--><td>x</table>",
    "table-form": "<table><form><input type=hidden><tr><td>x</form></table>",
    "table-hidden-input": "<table><input type=hidden name=a><input type=text name=b></table>",
    "table-in-p": "<p>a<table><tr><td>b</table>c",
    "table-td-without-tr": "<table><td>x<td>y</table>",
    "table-cell-end": "<table><tr><td>a</th><th>b</td>c</table>",
    "table-select": "<table><tr><td><select><option>a<td>b</select></table>",
    "table-script-style": "<table><script>1</script><style>2</style><tr><td>x</table>",
    "table-bs4-foster": "<table><td></tbody>A",
    "table-identical-whitespace": "<table> <tbody><tbody><ims></tbody> </table>",
    "table-eof": "<table><tr><td>unclosed",
    "table-template": "<table><template><tr><td>x</td></tr></template></table>",
    # --- foreign content ---------------------------------------------------
    "svg-basic": "<svg viewBox='0 0 10 10'><circle cx=5 cy=5 r=4 /></svg>",
    "svg-case-fixups": "<svg><foreignobject><p>x</p></foreignobject><lineargradient/>"
    "<clippath/><feGaussianBlur stddeviation=2 /></svg>",
    "svg-attr-case": "<svg preserveaspectratio=none viewbox=0 refx=1 glyphref=g></svg>",
    "svg-xlink": "<svg xmlns:xlink='http://www.w3.org/1999/xlink'><use xlink:href='#a' xlink:title=t/></svg>",
    "svg-xml-attrs": "<svg xml:lang=en xml:space=preserve xmlns=http://www.w3.org/2000/svg></svg>",
    "svg-title-html": "<svg><title><b>bold</b></title><desc><i>x</i></desc></svg>",
    "svg-breakout": "<svg><g><p>para</p></g></svg>",
    "svg-breakout-font": "<svg><font color=red>x</font><font size=1>y</font><font>z</font></svg>",
    "svg-cdata": "<svg><![CDATA[a < b && c]]></svg><p><![CDATA[bogus]]></p>",
    "svg-self-closing": "<svg><path d='M0 0'/><g/><rect/></svg>after",
    "svg-script": "<svg><script>if (a < b) {}</script></svg>",
    "svg-in-table": "<table><tr><td><svg><td>x</td></svg></td></tr></table>",
    "math-basic": "<math><mi>x</mi><mo>=</mo><mn>2</mn></math>",
    "math-annotation-html": "<math><annotation-xml encoding='text/html'><p>html</p></annotation-xml></math>",
    "math-annotation-svg": "<math><annotation-xml><svg><circle/></svg></annotation-xml></math>",
    "math-mtext": "<math><mtext><b>x</b><mglyph/><malignmark/></mtext></math>",
    "math-definitionurl": "<math definitionurl=x><mi definitionURL=y>z</mi></math>",
    "math-xlink": "<math xlink:href=x><mi>y</mi></math>",
    "svg-in-math": "<math><mi><svg><circle/></svg></mi></math>",
    "foreign-null": "<svg>\x00<g>\x00</g></svg>",
    "foreign-end-tag-mismatch": "<svg><g><circle></g></svg></p>x",
    "foreign-html-integration": "<svg><foreignObject><svg><foreignObject><p>deep</p></foreignObject></svg></foreignObject></svg>",
    # --- comments / doctypes / bogus ---------------------------------------
    "comment-basic": "<!-- hello -->",
    "comment-empty": "<!---->x<!--->y<!-->z",
    "comment-dashes": "<!-- a -- b --- c ---->",
    "comment-bang": "<!-- a --!>b",
    "comment-eof": "<p>x<!-- unterminated",
    "comment-nested-lt": "<!-- <!-- nested --> -->",
    "comment-in-head": "<head><!--h--></head><!--between--><body><!--b-->",
    "comment-before-html": "<!--first--><html><!--in-html--><head>",
    "bogus-comment-pi": "<?xml version='1.0'?><p>x",
    "bogus-comment-bang": "<!ELEMENT br EMPTY><p>x",
    "bogus-end-tag": "</ foo>x</#>y",
    "doctype-html5": "<!DOCTYPE html><p>x",
    "doctype-lower": "<!doctype html><p>x",
    "doctype-public": '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">',
    "doctype-public-only": '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">',
    "doctype-system-only": '<!DOCTYPE html SYSTEM "about:legacy-compat">',
    "doctype-empty-public": '<!DOCTYPE html PUBLIC "">',
    "doctype-empty-system": "<!DOCTYPE html SYSTEM ''>",
    "doctype-no-name": "<!DOCTYPE>",
    "doctype-bogus": "<!DOCTYPE html bogus stuff>",
    "doctype-eof": "<!DOCTYPE html PUBLIC 'a",
    "doctype-late": "<p>x<!DOCTYPE html>y",
    "doctype-quirks-table": "<table><p>quirks</table>",
    "doctype-standards-table": "<!DOCTYPE html><table><p>standards</table>",
    # --- characters / entities ---------------------------------------------
    "entities-named": "&amp; &lt; &gt; &quot; &apos; &copy; &nbsp; &hellip;",
    "entities-no-semicolon": "&amp &lt &copy &notit; &notin; &ampx",
    "entities-numeric": "&#65; &#x42; &#X43; &#0; &#x110000; &#xD800; &#128; &#x9F;",
    "entities-invalid": "&; &#; &#x; &foo; &#foo; &1",
    "entities-in-attr": "<a href='?a=1&b=2&copy=3&lt;&amp;' title=&quot;x&quot;>",
    "entities-long": "&" + "a" * 200 + ";",
    "entities-html5": "&RightArrowLeftArrow; &Nfr; &ngeqq; &fjlig; &sqcups;",
    "null-in-text": "a\x00b<p>c\x00d</p>",
    "null-in-attr": "<p a='x\x00y' \x00b=1>",
    "null-in-tag-name": "<p\x00q>x</p\x00q>",
    "null-in-comment": "<!--a\x00b-->",
    "control-chars": "a\x01b\x7fc\x80d\x9fe﷐f￿",
    "cr-lf": "a\r\nb\rc\n\r\nd<p>\r\n</p>",
    "bom-in-str": "﻿<p>x",
    "astral": "<p>\U0001F600 \U00010000 \U0010FFFD</p>",
    # --- attributes --------------------------------------------------------
    "attrs-duplicate": '<b b="20" a="1" b="10" a="2" a="3" a="4">x</b>',
    "attrs-case": "<p CLASS=a ID=b Data-X=c>",
    "attrs-unquoted": "<a href=foo/bar?x=1 title=a>",
    "attrs-unclosed-quote": '<div><a href="http://example.com/</a> never closed</div>',
    "attrs-boolean": "<input disabled checked=checked readonly=''>",
    "attrs-weird-names": "<p a<b=1 \"c=2 'd=3 e/f=4 =g>",
    "attrs-multivalued": "<p class='  a  b\tc\n' rel='x y' headers='h1 h2' accept-charset='u v'>",
    "attrs-unicode": "<a ☃=snowman>x</a>",
    "attrs-on-end-tag": "<p>x</p a=1>",
    "attrs-html-merge": "<html a=1><body><html a=2 b=3>",
    "attrs-meta-charset": "<meta charset='utf-8'><meta http-equiv=Content-Type content='text/html; charset=utf-8'>",
    # --- raw text / RCDATA -------------------------------------------------
    "script-content": "<script>if (a < b && c > d) { document.write('</p>'); }</script>",
    "script-comment-escape": "<script><!-- </script> --></script>x",
    "script-double-escape": "<script><!--<script></script>--></script>x",
    "style-content": "<style>p > a { content: '<b>'; }</style>",
    "title-rcdata": "<title>a <b> &amp; </title>",
    "textarea-rcdata": "<textarea>\n<b>&lt;x</b></textarea>",
    "textarea-leading-newline": "<textarea>\n\nx</textarea><pre>\n\ny</pre><listing>\nz</listing>",
    "xmp": "<xmp><b>&amp;</b></xmp>",
    "iframe-raw": "<iframe><p>x</p></iframe>",
    "noembed-noframes": "<noembed><b>x</b></noembed><noframes><b>y</b></noframes>",
    "noscript-body": "<noscript><p>x</p></noscript>",
    "noscript-head": "<head><noscript><link rel=a><p>x</p></noscript></head>",
    "plaintext": "<plaintext><b>&amp;</plaintext>",
    "script-eof": "<script>never closed",
    # --- templates ---------------------------------------------------------
    "template-body": "<body><template><p>x</p><td>y</td></template>",
    "template-nested": "<template><template><b>x</b></template></template>",
    "template-table-parts": "<template><tr><td>a</td></tr><col><caption>c</caption></template>",
    "template-shadowroot": "<div><template shadowrootmode=open><b>x</b></template></div>",
    # --- misc elements -----------------------------------------------------
    "void-elements": "<br><hr><img src=x><input><wbr><area><base><col><embed><param><source><track>",
    "void-self-closing": "<br/><img/><p/>x<div/>y",
    "image-to-img": "<image src=x>",
    "ruby": "<ruby>a<rb>b<rt>c<rp>d<rtc>e</ruby>",
    "select-nested": "<select><select>x</select>",
    "select-input": "<select><input><option>x",
    "select-content": "<select><div>a</div><span>b</span><option>c</select>",
    "frameset": "<frameset cols=50%><frame src=a><frameset><frame></frameset></frameset>",
    "frameset-after-body": "<body><frameset>",
    "frameset-after-content": "<p>x<frameset>",
    "menu-dir": "<menu><li>a</menu><dir><li>b</dir>",
    "search-dialog": "<p>a<search>b</search><p>c<dialog>d</dialog>",
    "custom-elements": "<my-element some-attr=x><other-el>y</other-el></my-element>",
    "unicode-tag-name": "<our☃>x</our☃>",
    "mixed-case-tags": "<DIV><Span>x</SPAN></div>",
    "form-controls": "<form><fieldset><legend>l</legend><label>n<input name=n></label>"
    "<button>b</button><textarea>t</textarea><select><option>o</select></fieldset></form>",
    # --- bs4 test documents ------------------------------------------------
    "bs4-extraction": "\n<html><head></head>\n<style>\n</style><script></script><body><p>hello</p></body></html>\n",
    "bs4-empty-comment": "\n<html>\n<body>\n<form>\n<!----><input type=\"text\">\n</form>\n</body>\n</html>\n",
    "bs4-reparent-children": "<div><a>aftermath<p><noscript>target</noscript>aftermath</a></p></div>",
    "bs4-cloned-multivalue": '<a class="my_class"><p></a>',
    "bs4-xml-decl": '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html>\n<p>foo</p>',
}


def _bad_document() -> str:
    from .vendor.bs4_tests import BAD_DOCUMENT

    return BAD_DOCUMENT


CASES["bs4-bad-document"] = _bad_document()

#: case id -> (classification, explanation)
#:
#: Classifications (see README "Known differences"):
#: * "intentional"  - soup5ever deliberately behaves differently
#: * "html5lib"     - html5lib / BS4's html5lib adapter deviates from the HTML
#:                    standard; soup5ever follows the standard
#: * "irrelevant"   - outside the compatibility contract
KNOWN_DIFFERENCES: dict[str, tuple[str, str]] = {
    "table-template": (
        "html5lib",
        "html5lib-python predates the <template> insertion mode rules for tables",
    ),
    "template-nested": (
        "html5lib",
        "html5lib puts a leading <template> in <body>; the standard puts it in <head>",
    ),
    "template-table-parts": (
        "html5lib",
        "html5lib puts a leading <template> in <body> and drops table parts inside it",
    ),
    "ruby": (
        "html5lib",
        "html5lib-python predates the <rb>/<rtc> implied end tag rules",
    ),
    "select-content": (
        "html5lib",
        "html5lib-python predates the 2025 <select> parsing changes that keep"
        " elements such as <div> inside <select>",
    ),
    "search-dialog": (
        "html5lib",
        "html5lib-python predates <search> and <dialog> closing an open <p>",
    ),
}
