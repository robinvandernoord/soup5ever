//! Character encoding sniffing for byte input.
//!
//! Implements the parts of the WHATWG "determining the character encoding"
//! algorithm that apply to a document handed to `BeautifulSoup` as bytes:
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

use encoding_rs::{Encoding, UTF_8, UTF_16BE, UTF_16LE, WINDOWS_1252, X_USER_DEFINED};

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

/// Get an encoding from a label.
///
/// See <https://encoding.spec.whatwg.org/#concept-encoding-get>.
#[must_use]
pub fn lookup(label: &[u8]) -> Option<&'static Encoding> {
    Encoding::for_label(label)
}

/// The adjustments from "change the encoding" and the prescan: a document
/// can't meaningfully declare itself UTF-16 from inside itself, and
/// x-user-defined is treated as windows-1252.
#[must_use]
pub fn adjust_declared(encoding: &'static Encoding) -> &'static Encoding {
    if encoding == UTF_16BE || encoding == UTF_16LE {
        UTF_8
    } else if encoding == X_USER_DEFINED {
        WINDOWS_1252
    } else {
        encoding
    }
}

/// Determine the encoding of a byte document (see the module docs).
#[must_use]
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
        if !bytes.is_ascii() && core::str::from_utf8(bytes).is_ok() {
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

const fn is_space(byte: u8) -> bool {
    matches!(byte, 0x09 | 0x0A | 0x0C | 0x0D | 0x20)
}

/// Prescan a byte stream to determine its encoding.
///
/// See <https://html.spec.whatwg.org/multipage/parsing.html#prescan-a-byte-stream-to-determine-its-encoding>.
#[must_use]
pub fn prescan(input: &[u8]) -> Option<&'static Encoding> {
    let bytes = &input[..input.len().min(1024)];
    let mut pos = 0;
    while pos < bytes.len() {
        let rest = &bytes[pos..];
        if rest.starts_with(b"<!--") {
            // Skip to the end of the comment.
            let end = find(&bytes[pos + 4..], b"-->")?;
            pos += 4 + end + 3;
            continue;
        }
        if rest.len() >= 6
            && rest[..5].eq_ignore_ascii_case(b"<meta")
            && (is_space(rest[5]) || rest[5] == b'/')
        {
            pos += 5;
            if let Some(encoding) = meta(bytes, &mut pos) {
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
            while pos < bytes.len() && !is_space(bytes[pos]) && bytes[pos] != b'>' {
                pos += 1;
            }
            while get_attribute(bytes, &mut pos).is_some() {}
            pos += 1;
            continue;
        }
        if rest.starts_with(b"<!") || rest.starts_with(b"</") || rest.starts_with(b"<?") {
            let end = rest.iter().position(|&byte| byte == b'>')?;
            pos += end + 1;
            continue;
        }
        pos += 1;
    }
    None
}

/// Process the attributes of a `<meta` tag starting at `pos`.
fn meta(bytes: &[u8], pos: &mut usize) -> Option<&'static Encoding> {
    let mut seen: Vec<Vec<u8>> = Vec::new();
    let mut got_pragma = false;
    let mut need_pragma: Option<bool> = None;
    let mut charset: Option<&'static Encoding> = None;
    while let Some((name, value)) = get_attribute(bytes, pos) {
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
                if charset.is_none()
                    && let Some(encoding) = extract_from_content(&value)
                {
                    charset = Some(encoding);
                    need_pragma = Some(true);
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

/// Get an attribute, as the prescan does.
///
/// See <https://html.spec.whatwg.org/multipage/parsing.html#concept-get-attributes-when-sniffing>.
///
/// Attribute names and values are ASCII-lowercased, as the spec requires.
fn get_attribute(bytes: &[u8], pos: &mut usize) -> Option<(Vec<u8>, Vec<u8>)> {
    while *pos < bytes.len() && (is_space(bytes[*pos]) || bytes[*pos] == b'/') {
        *pos += 1;
    }
    if *pos >= bytes.len() || bytes[*pos] == b'>' {
        return None;
    }
    let mut name = Vec::new();
    let mut value = Vec::new();
    // Attribute name.
    loop {
        let byte = *bytes.get(*pos)?;
        if byte == b'/' || byte == b'>' {
            return Some((name, value));
        }
        if byte == b'=' && !name.is_empty() {
            *pos += 1;
            break;
        }
        if is_space(byte) {
            // Spaces between the name and a possible '='.
            while *pos < bytes.len() && is_space(bytes[*pos]) {
                *pos += 1;
            }
            if bytes.get(*pos) != Some(&b'=') {
                return Some((name, value));
            }
            *pos += 1;
            break;
        }
        name.push(byte.to_ascii_lowercase());
        *pos += 1;
    }
    // Attribute value.
    while *pos < bytes.len() && is_space(bytes[*pos]) {
        *pos += 1;
    }
    let first = *bytes.get(*pos)?;
    if first == b'"' || first == b'\'' {
        *pos += 1;
        loop {
            let byte = *bytes.get(*pos)?;
            *pos += 1;
            if byte == first {
                return Some((name, value));
            }
            value.push(byte.to_ascii_lowercase());
        }
    }
    if first == b'>' {
        return Some((name, value));
    }
    loop {
        let byte = *bytes.get(*pos)?;
        if is_space(byte) || byte == b'>' {
            return Some((name, value));
        }
        value.push(byte.to_ascii_lowercase());
        *pos += 1;
    }
}

/// Extract a character encoding from a `<meta content>` value.
///
/// See <https://html.spec.whatwg.org/multipage/urls-and-fetching.html#algorithm-for-extracting-a-character-encoding-from-a-meta-element>.
#[must_use]
pub fn extract_from_content(content: &[u8]) -> Option<&'static Encoding> {
    let mut pos = 0;
    loop {
        let found = content[pos..]
            .windows(7)
            .position(|window| window.eq_ignore_ascii_case(b"charset"))?;
        pos += found + 7;
        while pos < content.len() && is_space(content[pos]) {
            pos += 1;
        }
        if content.get(pos) == Some(&b'=') {
            pos += 1;
            break;
        }
    }
    while pos < content.len() && is_space(content[pos]) {
        pos += 1;
    }
    let first = *content.get(pos)?;
    if first == b'"' || first == b'\'' {
        let end = content[pos + 1..].iter().position(|&byte| byte == first)?;
        return lookup(&content[pos + 1..pos + 1 + end]);
    }
    let end = content[pos..]
        .iter()
        .position(|&byte| is_space(byte) || byte == b';')
        .map_or(content.len(), |offset| pos + offset);
    lookup(&content[pos..end])
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

#[cfg(test)]
mod tests {
    use super::{Confidence, UTF_8, WINDOWS_1252, prescan, sniff};
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
        let from_bom = sniff(bom, &[]);
        assert_eq!(
            (from_bom.encoding, from_bom.confidence, from_bom.skip),
            (UTF_8, Confidence::Certain, 3)
        );
        let overridden = sniff(b"<meta charset=sjis>", &["iso-8859-2".into()]);
        assert_eq!(
            (overridden.encoding, overridden.confidence),
            (ISO_8859_2, Confidence::Certain)
        );
        let invalid = sniff(b"<meta charset=sjis>", &["not-an-encoding".into()]);
        assert_eq!(
            (invalid.encoding, invalid.confidence),
            (SHIFT_JIS, Confidence::Tentative)
        );
        assert_eq!(sniff("<p>é".as_bytes(), &[]).encoding, UTF_8);
        assert_eq!(sniff(b"<p>\xe9", &[]).encoding, WINDOWS_1252);
        assert_eq!(sniff(b"<p>ascii", &[]).encoding, WINDOWS_1252);
    }
}
