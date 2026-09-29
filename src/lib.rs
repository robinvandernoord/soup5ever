//! `soup5ever._soup5ever`: html5ever parsing for BeautifulSoup.
//!
//! The Python-facing surface is a single function, `build_tree`, called by
//! `soup5ever.HTML5everTreeBuilder.feed`.  Parsing (decoding, tokenizing,
//! tree construction, all of html5ever's tree fix-ups) runs in Rust with the
//! GIL released; the finished tree is then converted to BeautifulSoup objects
//! in one pass.

mod convert;
pub mod driver;
pub mod encoding;
pub mod sink;

use pyo3::exceptions::PyTypeError;
use pyo3::types::{
    PyAnyMethods, PyBytes, PyBytesMethods, PyModule, PyModuleMethods, PyString, PyStringMethods,
    PyTypeMethods,
};
use pyo3::{Bound, PyAny, PyResult, Python, pyfunction, pymodule, wrap_pyfunction};

/// Carries the arena out of `Python::detach`.
///
/// `detach` requires its return value to be `Send` because it is a generic
/// "run without the GIL" primitive.  The closure runs on the calling thread,
/// though, and the arena (whose tendrils use non-atomic reference counts) is
/// created inside the closure and only ever used by that same thread
/// afterwards, so nothing is actually shared across threads.
struct SameThread<T>(T);
unsafe impl<T> Send for SameThread<T> {}

/// Decode (if needed) and parse `markup`, then populate `soup`.
///
/// `classes` maps the roles in `convert::Classes` to the Python classes to
/// instantiate. `encodings` are candidate labels for the user's
/// `from_encoding` (byte input only). Returns the name of the encoding used
/// for byte input, `None` for str.
#[pyfunction]
#[pyo3(signature = (soup, builder, markup, classes, *, encodings, store_line_numbers))]
fn build_tree<'py>(
    py: Python<'py>,
    soup: &Bound<'py, PyAny>,
    builder: &Bound<'py, PyAny>,
    markup: &Bound<'py, PyAny>,
    classes: convert::Classes<'py>,
    encodings: Vec<String>,
    store_line_numbers: bool,
) -> PyResult<Option<String>> {
    let (arena, encoding) = if let Ok(s) = markup.cast::<PyString>() {
        let arena = match s.to_str() {
            Ok(text) => {
                py.detach(|| SameThread(driver::parse_str(text, store_line_numbers)))
                    .0
            }
            Err(_) => {
                // The str contains lone surrogates, which Rust strings can't
                // hold. Replace each with U+FFFD.
                let utf16 = s.call_method1("encode", ("utf-16-le", "surrogatepass"))?;
                let utf16 = utf16.cast::<PyBytes>()?.as_bytes();
                let units: Vec<u16> = utf16
                    .chunks_exact(2)
                    .map(|c| u16::from_le_bytes([c[0], c[1]]))
                    .collect();
                let text = String::from_utf16_lossy(&units);
                py.detach(|| SameThread(driver::parse_str(&text, store_line_numbers)))
                    .0
            }
        };
        (arena, None)
    } else if let Ok(b) = markup.cast::<PyBytes>() {
        let bytes = b.as_bytes();
        let (arena, enc) = py
            .detach(|| SameThread(driver::parse_bytes(bytes, &encodings, store_line_numbers)))
            .0;
        (arena, Some(enc.name().to_ascii_lowercase()))
    } else {
        return Err(PyTypeError::new_err(format!(
            "markup must be str or bytes, not {}",
            markup.get_type().name()?
        )));
    };
    convert::build(py, &arena, soup, builder, &classes, store_line_numbers)?;
    Ok(encoding)
}

/// Parse without building BeautifulSoup objects; returns the node count.
///
/// Private: used by the benchmarks to separate parsing cost from the cost
/// of creating BeautifulSoup objects.
#[pyfunction]
fn _parse_only(py: Python<'_>, markup: &Bound<'_, PyAny>) -> PyResult<usize> {
    if let Ok(s) = markup.cast::<PyString>() {
        let text = s.to_str()?;
        Ok(py.detach(|| driver::parse_str(text, true).nodes.len()))
    } else {
        let bytes = markup.cast::<PyBytes>()?.as_bytes();
        Ok(py.detach(|| driver::parse_bytes(bytes, &[], true).0.nodes.len()))
    }
}

#[pymodule]
fn _soup5ever(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_tree, m)?)?;
    m.add_function(wrap_pyfunction!(_parse_only, m)?)?;
    m.add("HTML5EVER_VERSION", "0.40")?;
    Ok(())
}
