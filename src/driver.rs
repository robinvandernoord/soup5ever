//! Drives the html5ever tokenizer and tree builder over a complete document.
//!
//! Two things here go beyond `html5ever::parse_document`:
//!
//! * Source positions.  `BeautifulSoup`'s html5lib builder records, for each
//!   tag, the line and column of html5lib's stream position when the element
//!   was created: for an element created from a start tag, the column of the
//!   tag's closing `>`; for elements implied by text, the end of that text.
//!   html5ever doesn't expose columns, so the input is fed to the tokenizer
//!   in chunks that end just after each `>` and just before each `<`, `&`
//!   and NUL.  A tag
//!   token is emitted exactly when its `>` is consumed, and a text run when
//!   its end is reached, i.e. at the end of a chunk, so every element created
//!   while a chunk is processed gets the chunk's end position.  Chunks are
//!   sub-tendrils of the input (no copying), and html5ever's tokenizer is
//!   chunk-boundary agnostic by design.
//!
//! * Encoding changes.  When the tree builder reports a `<meta charset>`
//!   while the encoding is still tentative, parsing stops and the caller
//!   re-decodes and re-parses the bytes, as the HTML spec (and html5lib) do.

use html5ever::TokenizerResult;
use html5ever::buffer_queue::BufferQueue;
use html5ever::interface::TreeSink;
use html5ever::tendril::StrTendril;
use html5ever::tokenizer::{Token, TokenSink, TokenSinkResult, Tokenizer, TokenizerOpts};
use html5ever::tree_builder::{TreeBuilder, TreeBuilderOpts};

use encoding_rs::Encoding;

use crate::encoding::{self, Confidence};
use crate::sink::{Arena, Sink};

/// A `TokenSink` that forwards to the tree builder, recording the raw
/// DOCTYPE token on the way (see `sink::PendingDoctype`) and dropping parse
/// errors.
struct Tap {
    tree_builder: TreeBuilder<u32, Sink>,
}

impl TokenSink for Tap {
    type Handle = u32;

    fn process_token(&self, token: Token, line_number: u64) -> TokenSinkResult<u32> {
        // Parse errors are of no use to BeautifulSoup, and letting them reach
        // the tree builder is actively harmful: html5ever resets its "ignore
        // the next LF" flag (set by <pre>, <listing>, <textarea>) on every
        // token, including these pseudo-tokens, so `<pre></>\n` would keep
        // the newline that the spec says to drop.
        if let Token::ParseError(_) = token {
            return TokenSinkResult::Continue;
        }
        if let Token::DoctypeToken(doctype) = &token {
            self.tree_builder.sink.set_pending_doctype((
                doctype.name.clone(),
                doctype.public_id.clone(),
                doctype.system_id.clone(),
            ));
        }
        self.tree_builder.process_token(token, line_number)
    }

    fn end(&self) {
        self.tree_builder.end();
    }

    fn adjusted_current_node_present_but_not_in_html_namespace(&self) -> bool {
        self.tree_builder
            .adjusted_current_node_present_but_not_in_html_namespace()
    }
}

/// The document declared a different encoding; re-parse with it.
#[derive(Debug)]
pub struct Reparse(pub &'static Encoding);

/// Tracks line/column over the input exactly like html5lib's input stream:
/// lines are 1-based, columns count code points since the last newline, and
/// CRLF / lone CR count as a single newline.
struct Position {
    line: u32,
    col: i64,
    after_cr: bool,
}

impl Position {
    fn advance(&mut self, bytes: &[u8]) {
        for &byte in bytes {
            match byte {
                b'\n' => {
                    if self.after_cr {
                        self.after_cr = false;
                    } else {
                        self.line += 1;
                        self.col = 0;
                    }
                }
                b'\r' => {
                    self.line += 1;
                    self.col = 0;
                    self.after_cr = true;
                }
                // UTF-8 continuation byte: same code point.
                continuation if continuation & 0xC0 == 0x80 => {}
                _ => {
                    self.col += 1;
                    self.after_cr = false;
                }
            }
        }
    }

    /// html5lib reports the column of the last consumed character.
    const fn current(&self) -> (u32, i64) {
        (self.line, self.col - 1)
    }
}

pub struct Options {
    pub track_positions: bool,
    /// Tentative encoding the input was decoded with (byte input only).
    pub tentative_encoding: Option<&'static Encoding>,
}

/// Parse a decoded document into an arena.
///
/// # Errors
///
/// `Reparse` if the document declares a different encoding while
/// `opts.tentative_encoding` is set: decode again with that one.
pub fn parse(input: &StrTendril, opts: &Options) -> Result<Arena, Reparse> {
    let tree_builder = TreeBuilder::new(
        Sink::new(),
        TreeBuilderOpts {
            // html5lib parses with scripting disabled, so <noscript> content
            // becomes ordinary markup.
            scripting_enabled: false,
            ..Default::default()
        },
    );
    let tokenizer = Tokenizer::new(
        Tap { tree_builder },
        TokenizerOpts {
            // A BOM in byte input has already been removed by the decoder; a
            // U+FEFF at the start of a str is content, as it is for html5lib.
            discard_bom: false,
            ..Default::default()
        },
    );
    let mut tentative = opts.tentative_encoding;
    let queue = BufferQueue::default();

    macro_rules! run {
        () => {
            loop {
                match tokenizer.feed(&queue) {
                    TokenizerResult::Done => break,
                    TokenizerResult::Script(_) => continue,
                    TokenizerResult::EncodingIndicator(label) => {
                        if let Some(current) = tentative {
                            if let Some(new) = encoding::lookup(label.as_bytes()) {
                                let new = encoding::adjust_declared(new);
                                if new == current {
                                    tentative = None;
                                } else {
                                    return Err(Reparse(new));
                                }
                            }
                        }
                    }
                }
            }
        };
    }

    let mut position = Position {
        line: 1,
        col: 0,
        after_cr: false,
    };
    if opts.track_positions {
        let bytes = input.as_bytes();
        let mut start = 0;
        while start < bytes.len() {
            let mut end = bytes.len();
            for (index, &byte) in bytes.iter().enumerate().skip(start) {
                if byte == b'>' {
                    end = index + 1;
                    break;
                }
                // html5lib hands a text run to the tree builder as soon as it
                // reaches one of these, before reading any further.
                if matches!(byte, b'<' | b'&' | b'\0') && index > start {
                    end = index;
                    break;
                }
            }
            position.advance(&bytes[start..end]);
            tokenizer
                .sink
                .tree_builder
                .sink
                .set_position(position.current());
            queue.push_back(input.subtendril(start as u32, (end - start) as u32));
            run!();
            start = end;
        }
    } else {
        queue.push_back(input.clone());
        run!();
    }
    if opts.track_positions {
        tokenizer
            .sink
            .tree_builder
            .sink
            .set_position(position.current());
    }
    tokenizer.end();
    Ok(tokenizer.sink.tree_builder.sink.finish())
}

/// Decode and parse a byte document.  Returns the tree and the encoding used.
#[must_use]
pub fn parse_bytes(
    bytes: &[u8],
    overrides: &[String],
    track_positions: bool,
) -> (Arena, &'static Encoding) {
    let sniffed = encoding::sniff(bytes, overrides);
    let mut encoding = sniffed.encoding;
    let mut confidence = sniffed.confidence;
    let body = &bytes[sniffed.skip..];
    loop {
        let (text, _had_errors) = encoding.decode_without_bom_handling(body);
        let opts = Options {
            track_positions,
            tentative_encoding: (confidence == Confidence::Tentative).then_some(encoding),
        };
        match parse(&StrTendril::from_slice(&text), &opts) {
            Ok(arena) => return (arena, encoding),
            Err(Reparse(new)) => {
                encoding = new;
                confidence = Confidence::Certain;
            }
        }
    }
}

/// Parse an already decoded document.
///
/// # Panics
///
/// Never: without a tentative encoding `parse` can't ask for a re-parse.
#[must_use]
pub fn parse_str(text: &str, track_positions: bool) -> Arena {
    let opts = Options {
        track_positions,
        tentative_encoding: None,
    };
    parse(&StrTendril::from_slice(text), &opts)
        .expect("without a tentative encoding there is nothing to re-parse")
}

#[cfg(test)]
mod tests {
    use core::fmt::Write as _;
    use core::iter::repeat_n;

    use super::{Arena, parse_bytes, parse_str};
    use crate::sink::{DOCUMENT, NodeData};

    /// A compact rendering of the arena: `name(children)`, `"text"`, etc.
    #[expect(
        clippy::use_debug,
        reason = "Debug output quotes and escapes text unambiguously"
    )]
    fn render(arena: &Arena, id: u32, out: &mut String) {
        for child in arena.children(id) {
            match &arena.nodes[child as usize].data {
                NodeData::Element {
                    name,
                    attrs,
                    template_contents,
                    ..
                } => {
                    out.push_str(&name.local);
                    for attr in attrs {
                        write!(out, " {}={}", &*attr.name.local, &*attr.value)
                            .expect("writing to a String");
                    }
                    out.push('(');
                    render(arena, child, out);
                    if *template_contents != crate::sink::NONE {
                        out.push_str("#content(");
                        render(arena, *template_contents, out);
                        out.push(')');
                    }
                    out.push(')');
                }
                NodeData::Text(text) => write!(out, "{:?}", &**text).expect("writing to a String"),
                NodeData::Comment(text) => {
                    write!(out, "<!--{}-->", &**text).expect("writing to a String");
                }
                NodeData::Doctype {
                    name,
                    public_id,
                    system_id,
                } => write!(
                    out,
                    "<!DOCTYPE {:?} {:?} {:?}>",
                    name.as_deref(),
                    public_id.as_deref(),
                    system_id.as_deref()
                )
                .expect("writing to a String"),
                NodeData::Document | NodeData::Fragment => {}
            }
        }
    }

    fn tree(html: &str) -> String {
        let arena = parse_str(html, true);
        let mut out = String::new();
        render(&arena, DOCUMENT, &mut out);
        out
    }

    fn positions(html: &str) -> Vec<(String, u32, i64)> {
        let arena = parse_str(html, true);
        arena
            .nodes
            .iter()
            .filter_map(|node| match &node.data {
                NodeData::Element {
                    name, line, pos, ..
                } => Some((name.local.to_string(), *line, *pos)),
                NodeData::Document
                | NodeData::Fragment
                | NodeData::Doctype { .. }
                | NodeData::Text(_)
                | NodeData::Comment(_) => None,
            })
            .collect()
    }

    #[test]
    fn implied_structure() {
        assert_eq!(tree("<p>Hello"), r#"html(head()body(p("Hello")))"#);
    }

    #[test]
    fn text_is_merged() {
        assert_eq!(tree("a<!---->b"), r#"html(head()body("a"<!---->"b"))"#);
        assert_eq!(tree("a&amp;b</x>c"), r#"html(head()body("a&bc"))"#);
    }

    #[test]
    fn foster_parenting() {
        assert_eq!(
            tree("<table>x<tr><td>y</table>"),
            r#"html(head()body("x"table(tbody(tr(td("y"))))))"#
        );
    }

    #[test]
    fn adoption_agency() {
        assert_eq!(
            tree("<b>1<p>2</b>3</p>"),
            r#"html(head()body(b("1")p(b("2")"3")))"#
        );
    }

    #[test]
    fn template_contents_are_a_fragment() {
        assert_eq!(
            tree("<template><td>x</td></template>"),
            r#"html(head(template(#content(td("x"))))body())"#
        );
    }

    #[test]
    fn doctype_keeps_missing_vs_empty_ids() {
        assert_eq!(
            tree("<!DOCTYPE html PUBLIC \"\">"),
            r#"<!DOCTYPE Some("html") Some("") None>html(head()body())"#
        );
        assert_eq!(
            tree("<!DOCTYPE>"),
            "<!DOCTYPE None None None>html(head()body())"
        );
    }

    #[test]
    fn html_attributes_merge() {
        assert_eq!(
            tree("<html a=1><html a=2 b=3>"),
            "html a=1 b=3(head()body())"
        );
    }

    #[test]
    fn parse_errors_do_not_eat_the_ignored_newline() {
        // html5ever resets "ignore next LF" on parse-error pseudo-tokens.
        assert_eq!(tree("<pre></>\nx"), r#"html(head()body(pre("x")))"#);
    }

    #[test]
    fn chunking_does_not_change_the_tree() {
        for html in [
            "<p>a&amp;b&notin;c&#x41;<b>x</p>y",
            "<table>x<tr>y<td>z</table>",
            "<script>a<b>&amp;</script><textarea>\n&lt;</textarea>",
            "a\r\nb\rc\0d<svg><![CDATA[<x>]]></svg>",
        ] {
            let with = parse_str(html, true);
            let without = parse_str(html, false);
            let (mut chunked, mut whole) = (String::new(), String::new());
            render(&with, DOCUMENT, &mut chunked);
            render(&without, DOCUMENT, &mut whole);
            assert_eq!(chunked, whole, "{html:?}");
        }
    }

    #[test]
    fn positions_follow_html5lib() {
        assert_eq!(
            positions("\n   <p>\n\n<b>"),
            vec![
                ("html".into(), 2, 5),
                ("head".into(), 2, 5),
                ("body".into(), 2, 5),
                ("p".into(), 2, 5),
                ("b".into(), 4, 2),
            ]
        );
        // Implied by text: the end of the text run.
        assert_eq!(positions("FOO<!-- x -->")[0], ("html".into(), 1, 2));
        // CRLF is one line break; columns count code points.
        assert_eq!(positions("a\r\nb\rc<p>é<b>")[4], ("b".into(), 3, 7));
    }

    #[test]
    fn adoption_agency_clones_have_no_position() {
        let found = positions("<b>1<p>2</b>3</p>");
        // html, head, body, b, p, then the clone of b made at </b>; line 0
        // means "no position".
        assert_eq!((found[5].0.as_str(), found[5].1), ("b", 0));
        assert_ne!(found[3].1, 0);
    }

    #[test]
    fn meta_charset_requests_reparse() {
        let bytes = b"<meta charset=iso-8859-2><p>\xb1";
        let (arena, declared) = parse_bytes(bytes, &[], false);
        assert_eq!(declared, encoding_rs::ISO_8859_2);
        let mut out = String::new();
        render(&arena, DOCUMENT, &mut out);
        assert!(out.contains("\"\u{105}\""), "{out}");
        // Late declaration: beyond the prescan, found by the tree builder.
        let mut late = b"<!--".to_vec();
        late.extend(repeat_n(b'x', 1100));
        late.extend_from_slice(b"--><meta charset=iso-8859-2><p>\xb1");
        assert_eq!(parse_bytes(&late, &[], false).1, encoding_rs::ISO_8859_2);
        // A certain encoding (from the caller) is never changed.
        let (_, overridden) = parse_bytes(bytes, &["windows-1252".into()], false);
        assert_eq!(overridden, encoding_rs::WINDOWS_1252);
    }
}
