//! Character encoding sniffing for byte input.
//!
//! Implements the parts of the WHATWG "determining the character encoding"
//! algorithm that apply to a document handed to BeautifulSoup as bytes:
//!
//! 1. a byte order mark (confidence: certain);
//! 2. the user's `from_encoding` override (certain);
//! 3. the `<meta>` prescan of the first 1024 bytes (tentative);
//! 4. autodetection: bytes that are valid, non-ASCII UTF-8 are UTF-8 (tentative);
//! 5. the default, windows-1252 (tentative).
//!
//! Steps 1-3 and 5 match html5lib.  Step 4 is where html5lib consults
//! `chardet` if it happens to be installed; we use a deterministic UTF-8
//! validity check instead.  A tentative encoding can later be replaced when
//! the tree builder sees a `<meta charset>` (see `driver.rs`).

use encoding_rs::{Encoding, UTF_16BE, UTF_16LE, UTF_8, WINDOWS_1252, X_USER_DEFINED};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Confidence {
    Tentative,
    Certain,
}

pub struct Sniffed {
    pub encoding: &'static Encoding,
    pub confidence: Confidence,
    /// Number of leading bytes (a BOM) to skip before decoding.
    pub skip: usize,
}

/// <https://encoding.spec.whatwg.org/#concept-encoding-get>
pub fn lookup(label: &[u8]) -> Option<&'static Encoding> {
    Encoding::for_label(label)
}

/// The adjustments from "change the encoding" and the prescan: a document
/// can't meaningfully declare itself UTF-16 from inside itself, and
/// x-user-defined is treated as windows-1252.
pub fn adjust_declared(encoding: &'static Encoding) -> &'static Encoding {
    if encoding == UTF_16BE || encoding == UTF_16LE {
        UTF_8
    } else if encoding == X_USER_DEFINED {
        WINDOWS_1252
    } else {
        encoding
    }
}

pub fn sniff(bytes: &[u8], overrides: &[String]) -> Sniffed {
    if let Some((encoding, skip)) = Encoding::for_bom(bytes) {
        return Sniffed {
            encoding,
            confidence: Confidence::Certain,
            skip,
        };
    }
    for label in overrides {
        if let Some(encoding) = lookup(label.as_bytes()) {
            return Sniffed {
                encoding,
                confidence: Confidence::Certain,
                skip: 0,
            };
        }
    }
    let encoding = prescan(bytes).unwrap_or_else(|| {
        if !bytes.is_ascii() && std::str::from_utf8(bytes).is_ok() {
            UTF_8
        } else {
            WINDOWS_1252
        }
    });
    Sniffed {
        encoding,
        confidence: Confidence::Tentative,
        skip: 0,
    }
}

fn is_space(b: u8) -> bool {
    matches!(b, 0x09 | 0x0A | 0x0C | 0x0D | 0x20)
}

/// <https://html.spec.whatwg.org/multipage/parsing.html#prescan-a-byte-stream-to-determine-its-encoding>
pub fn prescan(input: &[u8]) -> Option<&'static Encoding> {
    let b = &input[..input.len().min(1024)];
    let mut pos = 0;
    while pos < b.len() {
        let rest = &b[pos..];
        if rest.starts_with(b"<!--") {
            // Skip to the end of the comment.
            let end = find(&b[pos + 4..], b"-->")?;
            pos += 4 + end + 3;
            continue;
        }
        if rest.len() >= 6
            && rest[..5].eq_ignore_ascii_case(b"<meta")
            && (is_space(rest[5]) || rest[5] == b'/')
        {
            pos += 5;
            if let Some(encoding) = meta(b, &mut pos) {
                return Some(encoding);
            }
            continue;
        }
        if rest.len() >= 2
            && rest[0] == b'<'
            && (rest[1].is_ascii_alphabetic()
                || (rest[1] == b'/' && rest.len() >= 3 && rest[2].is_ascii_alphabetic()))
        {
            // A start or end tag: skip its name and attributes.
            pos += 1;
            while pos < b.len() && !is_space(b[pos]) && b[pos] != b'>' {
                pos += 1;
            }
            while get_attribute(b, &mut pos).is_some() {}
            pos += 1;
            continue;
        }
        if rest.starts_with(b"<!") || rest.starts_with(b"</") || rest.starts_with(b"<?") {
            let end = rest.iter().position(|&c| c == b'>')?;
            pos += end + 1;
            continue;
        }
        pos += 1;
    }
    None
}

/// Process the attributes of a `<meta` tag starting at `pos`.
fn meta(b: &[u8], pos: &mut usize) -> Option<&'static Encoding> {
    let mut seen: Vec<Vec<u8>> = Vec::new();
    let mut got_pragma = false;
    let mut need_pragma: Option<bool> = None;
    let mut charset: Option<&'static Encoding> = None;
    while let Some((name, value)) = get_attribute(b, pos) {
        if seen.contains(&name) {
            continue;
        }
        match name.as_slice() {
            b"http-equiv" => {
                if value == b"content-type" {
                    got_pragma = true;
                }
            }
            b"content" => {
                if charset.is_none() {
                    if let Some(enc) = extract_from_content(&value) {
                        charset = Some(enc);
                        need_pragma = Some(true);
                    }
                }
            }
            b"charset" => {
                charset = lookup(&value);
                need_pragma = Some(false);
            }
            _ => {}
        }
        seen.push(name);
    }
    match need_pragma {
        None => None,
        Some(true) if !got_pragma => None,
        _ => charset.map(adjust_declared),
    }
}

/// <https://html.spec.whatwg.org/multipage/parsing.html#concept-get-attributes-when-sniffing>
///
/// Attribute names and values are ASCII-lowercased, as the spec requires.
fn get_attribute(b: &[u8], pos: &mut usize) -> Option<(Vec<u8>, Vec<u8>)> {
    while *pos < b.len() && (is_space(b[*pos]) || b[*pos] == b'/') {
        *pos += 1;
    }
    if *pos >= b.len() || b[*pos] == b'>' {
        return None;
    }
    let mut name = Vec::new();
    let mut value = Vec::new();
    // Attribute name.
    loop {
        let c = *b.get(*pos)?;
        if c == b'=' && !name.is_empty() {
            *pos += 1;
            break;
        } else if is_space(c) {
            // Spaces between the name and a possible '='.
            while *pos < b.len() && is_space(b[*pos]) {
                *pos += 1;
            }
            if b.get(*pos) != Some(&b'=') {
                return Some((name, value));
            }
            *pos += 1;
            break;
        } else if c == b'/' || c == b'>' {
            return Some((name, value));
        } else {
            name.push(c.to_ascii_lowercase());
        }
        *pos += 1;
    }
    // Attribute value.
    while *pos < b.len() && is_space(b[*pos]) {
        *pos += 1;
    }
    let c = *b.get(*pos)?;
    if c == b'"' || c == b'\'' {
        *pos += 1;
        loop {
            let d = *b.get(*pos)?;
            *pos += 1;
            if d == c {
                return Some((name, value));
            }
            value.push(d.to_ascii_lowercase());
        }
    }
    if c == b'>' {
        return Some((name, value));
    }
    loop {
        let d = *b.get(*pos)?;
        if is_space(d) || d == b'>' {
            return Some((name, value));
        }
        value.push(d.to_ascii_lowercase());
        *pos += 1;
    }
}

/// <https://html.spec.whatwg.org/multipage/urls-and-fetching.html#algorithm-for-extracting-a-character-encoding-from-a-meta-element>
pub fn extract_from_content(s: &[u8]) -> Option<&'static Encoding> {
    let mut pos = 0;
    loop {
        let found = s[pos..]
            .windows(7)
            .position(|w| w.eq_ignore_ascii_case(b"charset"))?;
        pos += found + 7;
        while pos < s.len() && is_space(s[pos]) {
            pos += 1;
        }
        if s.get(pos) == Some(&b'=') {
            pos += 1;
            break;
        }
    }
    while pos < s.len() && is_space(s[pos]) {
        pos += 1;
    }
    let c = *s.get(pos)?;
    if c == b'"' || c == b'\'' {
        let end = s[pos + 1..].iter().position(|&d| d == c)?;
        return lookup(&s[pos + 1..pos + 1 + end]);
    }
    let end = s[pos..]
        .iter()
        .position(|&d| is_space(d) || d == b';')
        .map_or(s.len(), |e| pos + e);
    lookup(&s[pos..end])
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

#[cfg(test)]
mod tests {
    use super::*;
    use encoding_rs::{ISO_8859_2, SHIFT_JIS};

    #[test]
    fn prescan_meta_charset() {
        assert_eq!(prescan(b"<meta charset=\"sjis\">"), Some(SHIFT_JIS));
        assert_eq!(prescan(b"<META CHARSET='iso-8859-2'>"), Some(ISO_8859_2));
        assert_eq!(prescan(b"<meta charset=utf-16le>"), Some(UTF_8));
        assert_eq!(
            prescan(b"<meta charset=x-user-defined>"),
            Some(WINDOWS_1252)
        );
    }

    #[test]
    fn prescan_http_equiv() {
        let doc = b"<meta http-equiv=\"Content-Type\" content=\"text/html; charset=ISO-8859-2\">";
        assert_eq!(prescan(doc), Some(ISO_8859_2));
        // Without the pragma, a content attribute is ignored.
        assert_eq!(
            prescan(b"<meta content=\"text/html; charset=ISO-8859-2\">"),
            None
        );
    }

    #[test]
    fn prescan_skips_comments_and_tags() {
        assert_eq!(
            prescan(b"<!-- <meta charset=sjis> --><p title='<meta charset=sjis>'>"),
            None
        );
        assert_eq!(prescan(b"<!-- x --><meta charset=sjis>"), Some(SHIFT_JIS));
        assert_eq!(prescan(b"<!-- unterminated <meta charset=sjis>"), None);
    }

    #[test]
    fn prescan_only_looks_at_1024_bytes() {
        let mut doc = vec![b' '; 1024];
        doc.extend_from_slice(b"<meta charset=sjis>");
        assert_eq!(prescan(&doc), None);
    }

    #[test]
    fn sniff_order() {
        let bom = b"\xef\xbb\xbf<meta charset=sjis>";
        let s = sniff(bom, &[]);
        assert_eq!(
            (s.encoding, s.confidence, s.skip),
            (UTF_8, Confidence::Certain, 3)
        );
        let s = sniff(b"<meta charset=sjis>", &["iso-8859-2".into()]);
        assert_eq!(
            (s.encoding, s.confidence),
            (ISO_8859_2, Confidence::Certain)
        );
        let s = sniff(b"<meta charset=sjis>", &["not-an-encoding".into()]);
        assert_eq!(
            (s.encoding, s.confidence),
            (SHIFT_JIS, Confidence::Tentative)
        );
        assert_eq!(sniff("<p>é".as_bytes(), &[]).encoding, UTF_8);
        assert_eq!(sniff(b"<p>\xe9", &[]).encoding, WINDOWS_1252);
        assert_eq!(sniff(b"<p>ascii", &[]).encoding, WINDOWS_1252);
    }
}
