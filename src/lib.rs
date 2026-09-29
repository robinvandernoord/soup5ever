//! `soup5ever._soup5ever`: html5ever parsing for `BeautifulSoup`.
//!
//! The Python-facing surface is a single function, `build_tree`, called by
//! `soup5ever.HTML5everTreeBuilder.feed`.  Parsing (decoding, tokenizing,
//! tree construction, all of html5ever's tree fix-ups) runs in Rust with the
//! GIL released; the finished tree is then converted to `BeautifulSoup` objects
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
#[expect(
    clippy::non_send_fields_in_send_ty,
    reason = "the wrapper exists to carry a !Send value out of Python::detach on the same thread"
)]
// SAFETY: see above; the value never leaves the thread it was created on.
unsafe impl<T> Send for SameThread<T> {}

/// Decode (if needed) and parse `markup`, then populate `soup`.
///
/// `classes` maps the roles in `convert::Classes` to the Python classes to
/// instantiate. `encodings` are candidate labels for the user's
/// `from_encoding` (byte input only). Returns the name of the encoding used
/// for byte input, `None` for str.
#[pyfunction]
#[pyo3(signature = (soup, builder, markup, classes, *, encodings, store_line_numbers))]
#[expect(
    clippy::needless_pass_by_value,
    reason = "PyO3 extracts arguments into owned values"
)]
fn build_tree<'py>(
    py: Python<'py>,
    soup: &Bound<'py, PyAny>,
    builder: &Bound<'py, PyAny>,
    markup: &Bound<'py, PyAny>,
    classes: convert::Classes<'py>,
    encodings: Vec<String>,
    store_line_numbers: bool,
) -> PyResult<Option<String>> {
    let (arena, encoding) = if let Ok(string) = markup.cast::<PyString>() {
        let arena = if let Ok(text) = string.to_str() {
            py.detach(|| SameThread(driver::parse_str(text, store_line_numbers)))
                .0
        } else {
            // The str contains lone surrogates, which Rust strings can't
            // hold. Replace each with U+FFFD.
            let encoded = string.call_method1("encode", ("utf-16-le", "surrogatepass"))?;
            let units: Vec<u16> = encoded
                .cast::<PyBytes>()?
                .as_bytes()
                .as_chunks::<2>()
                .0
                .iter()
                .map(|&pair| {
                    #[expect(
                        clippy::little_endian_bytes,
                        reason = "Python encoded it as UTF-16-LE"
                    )]
                    u16::from_le_bytes(pair)
                })
                .collect();
            let text = String::from_utf16_lossy(&units);
            py.detach(|| SameThread(driver::parse_str(&text, store_line_numbers)))
                .0
        };
        (arena, None)
    } else if let Ok(pybytes) = markup.cast::<PyBytes>() {
        let bytes = pybytes.as_bytes();
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

/// Parse without building `BeautifulSoup` objects; returns the node count.
///
/// Private: used by the benchmarks to separate parsing cost from the cost
/// of creating `BeautifulSoup` objects.
#[pyfunction]
fn _parse_only(py: Python<'_>, markup: &Bound<'_, PyAny>) -> PyResult<usize> {
    if let Ok(string) = markup.cast::<PyString>() {
        let text = string.to_str()?;
        Ok(py.detach(|| driver::parse_str(text, true).nodes.len()))
    } else {
        let bytes = markup.cast::<PyBytes>()?.as_bytes();
        Ok(py.detach(|| driver::parse_bytes(bytes, &[], true).0.nodes.len()))
    }
}

#[pymodule]
fn _soup5ever(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(build_tree, module)?)?;
    module.add_function(wrap_pyfunction!(_parse_only, module)?)?;
    module.add("HTML5EVER_VERSION", "0.40")?;
    Ok(())
}
