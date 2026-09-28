//! Drives the html5ever tokenizer and tree builder over a complete document.
//!
//! Two things here go beyond `html5ever::parse_document`:
//!
//! * Source positions.  BeautifulSoup's html5lib builder records, for each
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

use html5ever::buffer_queue::BufferQueue;
use html5ever::tendril::StrTendril;
use html5ever::tokenizer::{Token, TokenSink, TokenSinkResult, Tokenizer, TokenizerOpts};
use html5ever::tree_builder::{TreeBuilder, TreeBuilderOpts};
use html5ever::interface::TreeSink;
use html5ever::TokenizerResult;

use encoding_rs::Encoding;

use crate::encoding::{self, Confidence};
use crate::sink::{Arena, Sink};

/// A `TokenSink` that forwards to the tree builder, recording the raw
/// DOCTYPE token on the way (see `sink::PendingDoctype`).
struct Tap {
    tree_builder: TreeBuilder<u32, Sink>,
}

impl TokenSink for Tap {
    type Handle = u32;

    fn process_token(&self, token: Token, line_number: u64) -> TokenSinkResult<u32> {
        let sink = &self.tree_builder.sink;
        if let Token::DoctypeToken(ref doctype) = token {
            *sink.pending_doctype.borrow_mut() = Some((
                doctype.name.clone(),
                doctype.public_id.clone(),
                doctype.system_id.clone(),
            ));
        }
        self.tree_builder.process_token(token, line_number)
    }

    fn end(&self) {
        self.tree_builder.end()
    }

    fn adjusted_current_node_present_but_not_in_html_namespace(&self) -> bool {
        self.tree_builder
            .adjusted_current_node_present_but_not_in_html_namespace()
    }
}

pub enum Outcome {
    Done(Arena),
    /// The document declared a different encoding; re-parse with it.
    Reparse(&'static Encoding),
}

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
        for &b in bytes {
            match b {
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
                b if b & 0xC0 == 0x80 => {}
                _ => {
                    self.col += 1;
                    self.after_cr = false;
                }
            }
        }
    }

    /// html5lib reports the column of the last consumed character.
    fn current(&self) -> (u32, i64) {
        (self.line, self.col - 1)
    }
}

pub struct Options {
    pub track_positions: bool,
    /// Tentative encoding the input was decoded with (byte input only).
    pub tentative_encoding: Option<&'static Encoding>,
}

pub fn parse(input: StrTendril, opts: &Options) -> Outcome {
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
    let sink = &tokenizer.sink.tree_builder.sink;

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
                                    return Outcome::Reparse(new);
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
        let mut start = 0usize;
        while start < bytes.len() {
            let mut end = bytes.len();
            for (i, &b) in bytes.iter().enumerate().skip(start) {
                if b == b'>' {
                    end = i + 1;
                    break;
                }
                // html5lib hands a text run to the tree builder as soon as it
                // reaches one of these, before reading any further.
                if matches!(b, b'<' | b'&' | b'\0') && i > start {
                    end = i;
                    break;
                }
            }
            position.advance(&bytes[start..end]);
            sink.position.set(position.current());
            queue.push_back(input.subtendril(start as u32, (end - start) as u32));
            run!();
            start = end;
        }
    } else {
        queue.push_back(input.clone());
        run!();
    }
    if opts.track_positions {
        sink.position.set(position.current());
    }
    tokenizer.end();
    Outcome::Done(tokenizer.sink.tree_builder.sink.finish())
}

/// Decode and parse a byte document.  Returns the tree and the encoding used.
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
        match parse(StrTendril::from_slice(&text), &opts) {
            Outcome::Done(arena) => return (arena, encoding),
            Outcome::Reparse(new) => {
                encoding = new;
                confidence = Confidence::Certain;
            }
        }
    }
}

pub fn parse_str(text: &str, track_positions: bool) -> Arena {
    let opts = Options {
        track_positions,
        tentative_encoding: None,
    };
    match parse(StrTendril::from_slice(text), &opts) {
        Outcome::Done(arena) => arena,
        Outcome::Reparse(_) => unreachable!("str input never changes encoding"),
    }
}
