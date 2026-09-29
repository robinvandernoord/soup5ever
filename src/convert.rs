//! Conversion of the finished arena into `BeautifulSoup` objects.
//!
//! The tree is walked once, in document order.  Each node becomes the same
//! kind of object `BeautifulSoup`'s html5lib builder would create (`Tag` via
//! the soup's element class, `NavigableString`, `Comment`, `Doctype`), and
//! the five linkage attributes `BeautifulSoup` maintains (`parent`,
//! `previous_element`/`next_element`, `previous_sibling`/`next_sibling`) plus
//! `contents` are set directly.  Because the tree is final, every node is
//! linked exactly once and the linkage is correct by construction; nothing is
//! ever moved after it has been created.

use std::collections::HashMap;

use html5ever::tendril::StrTendril;
use html5ever::{LocalName, Namespace, QualName};
use pyo3::exceptions::PyRuntimeError;
use pyo3::types::{PyAnyMethods, PyDict, PyDictMethods, PyList, PyListMethods, PyString, PyTuple};
use pyo3::{Bound, FromPyObject, PyAny, PyErr, PyResult, Python, intern};

use crate::sink::{Arena, DOCUMENT, NONE, NodeData};

/// The Python classes the conversion instantiates, passed from Python as a
/// dict (see `HTML5everTreeBuilder.feed`).
#[derive(FromPyObject)]
pub struct Classes<'py> {
    #[pyo3(item)]
    pub tag: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub string: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub comment: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub doctype: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub namespaced_attribute: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub attribute_dict: Bound<'py, PyAny>,
    /// Whether `attribute_dict` stores str values unchanged, so it can be
    /// filled with `PyDict_SetItem` instead of its Python `__setitem__`.
    #[pyo3(item)]
    pub attribute_dict_is_plain: bool,
}

struct Converter<'py, 'refs> {
    py: Python<'py>,
    builder: &'refs Bound<'py, PyAny>,
    classes: &'refs Classes<'py>,
    store_line_numbers: bool,
    local_names: HashMap<LocalName, Bound<'py, PyString>>,
    namespaces: HashMap<Namespace, Bound<'py, PyString>>,
    attr_names: HashMap<QualName, Bound<'py, PyAny>>,
}

impl<'py> Converter<'py, '_> {
    fn local_name(&mut self, name: &LocalName) -> Bound<'py, PyString> {
        let py = self.py;
        self.local_names
            .entry(name.clone())
            .or_insert_with(|| PyString::new(py, name))
            .clone()
    }

    fn namespace(&mut self, ns: &Namespace) -> Bound<'py, PyString> {
        let py = self.py;
        self.namespaces
            .entry(ns.clone())
            .or_insert_with(|| PyString::new(py, ns))
            .clone()
    }

    /// Attribute names are plain strings, except for foreign attributes
    /// (`xlink:href`, `xml:lang`, `xmlns:xlink`, ...), which become
    /// `NamespacedAttribute`s exactly as the html5lib builder makes them.
    fn attr_name(&mut self, name: &QualName) -> PyResult<Bound<'py, PyAny>> {
        if let Some(cached) = self.attr_names.get(name) {
            return Ok(cached.clone());
        }
        let py = self.py;
        let obj = if name.ns.is_empty() {
            PyString::new(py, &name.local).into_any()
        } else {
            // html5ever gives `xmlns` an empty prefix; html5lib (and
            // NamespacedAttribute's own convention) use None.
            let prefix = name
                .prefix
                .as_ref()
                .filter(|prefix| !prefix.is_empty())
                .map(|prefix| PyString::new(py, prefix));
            self.classes.namespaced_attribute.call1((
                prefix,
                PyString::new(py, &name.local),
                PyString::new(py, &name.ns),
            ))?
        };
        self.attr_names.insert(name.clone(), obj.clone());
        Ok(obj)
    }

    fn element(
        &mut self,
        name: &QualName,
        attrs: &[html5ever::Attribute],
        line: u32,
        pos: i64,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = self.py;
        let py_name = self.local_name(&name.local);
        let py_ns = self.namespace(&name.ns);
        let py_attrs = if attrs.is_empty() {
            py.None().into_bound(py)
        } else {
            // An instance of the builder's attribute dict class, filled the
            // way the html5lib builder fills it: through `__setitem__`.
            let container = self.classes.attribute_dict.call0()?;
            if self.classes.attribute_dict_is_plain {
                let dict = container.cast::<PyDict>()?;
                for attr in attrs {
                    dict.set_item(self.attr_name(&attr.name)?, PyString::new(py, &attr.value))?;
                }
            } else {
                for attr in attrs {
                    container
                        .set_item(self.attr_name(&attr.name)?, PyString::new(py, &attr.value))?;
                }
            }
            container
        };
        let kwargs = PyDict::new(py);
        if self.store_line_numbers && line != 0 {
            kwargs.set_item(intern!(py, "sourceline"), line)?;
            kwargs.set_item(intern!(py, "sourcepos"), pos)?;
        } else {
            kwargs.set_item(intern!(py, "sourceline"), py.None())?;
            kwargs.set_item(intern!(py, "sourcepos"), py.None())?;
        }
        let args = PyTuple::new(
            py,
            [
                py.None().into_bound(py),
                self.builder.clone(),
                py_name.into_any(),
                py_ns.into_any(),
                py.None().into_bound(py),
                py_attrs,
            ],
        )?;
        self.classes.tag.call(args, Some(&kwargs))
    }

    fn doctype(
        &self,
        name: Option<&StrTendril>,
        public_id: Option<&StrTendril>,
        system_id: Option<&StrTendril>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = self.py;
        let to_py = |value: Option<&StrTendril>| value.map(|text| PyString::new(py, text));
        self.classes.doctype.call_method1(
            intern!(py, "for_name_and_ids"),
            (
                to_py(name).unwrap_or_else(|| PyString::new(py, "")),
                to_py(public_id),
                to_py(system_id),
            ),
        )
    }
}

struct Frame<'py> {
    next_child: u32,
    parent: Bound<'py, PyAny>,
    contents: Bound<'py, PyList>,
    last_sibling: Option<Bound<'py, PyAny>>,
}

/// Populate `soup` (already reset by `BeautifulSoup`) from `arena`.
///
/// # Errors
///
/// Any exception raised while creating or linking the Python objects.
pub fn build<'py>(
    py: Python<'py>,
    arena: &Arena,
    soup: &Bound<'py, PyAny>,
    builder: &Bound<'py, PyAny>,
    classes: &Classes<'py>,
    store_line_numbers: bool,
) -> PyResult<()> {
    let mut conv = Converter {
        py,
        builder,
        classes,
        store_line_numbers,
        local_names: HashMap::new(),
        namespaces: HashMap::new(),
        attr_names: HashMap::new(),
    };

    let a_parent = intern!(py, "parent");
    let a_prev_el = intern!(py, "previous_element");
    let a_next_el = intern!(py, "next_element");
    let a_prev_sib = intern!(py, "previous_sibling");
    let a_next_sib = intern!(py, "next_sibling");
    let a_contents = intern!(py, "contents");

    let nodes = &arena.nodes;
    // html5lib's adapter links the soup and the first top-level node through
    // next_element/previous_element, except when that node is the doctype
    // (which it inserts by a different route). Keep that behavior.
    let first = nodes[DOCUMENT as usize].first_child;
    let mut previous: Option<Bound<'py, PyAny>> = (first != NONE
        && !matches!(nodes[first as usize].data, NodeData::Doctype { .. }))
    .then(|| soup.clone());
    let mut stack: Vec<Frame<'py>> = vec![Frame {
        next_child: nodes[DOCUMENT as usize].first_child,
        parent: soup.clone(),
        contents: soup.getattr(a_contents)?.cast_into::<PyList>()?,
        last_sibling: None,
    }];

    while let Some(frame) = stack.last_mut() {
        let id = frame.next_child;
        if id == NONE {
            stack.pop();
            continue;
        }
        let node = &nodes[id as usize];
        frame.next_child = node.next_sibling;

        let mut children = NONE;
        let obj = match &node.data {
            NodeData::Element {
                name,
                attrs,
                template_contents,
                line,
                pos,
                ..
            } => {
                // Template contents are a separate fragment in the HTML DOM;
                // BeautifulSoup (like html5lib) has no such concept and keeps
                // them as the template's children.
                children = if *template_contents == NONE {
                    node.first_child
                } else {
                    nodes[*template_contents as usize].first_child
                };
                conv.element(name, attrs, *line, *pos)?
            }
            NodeData::Text(text) => classes.string.call1((PyString::new(py, text),))?,
            NodeData::Comment(text) => classes.comment.call1((PyString::new(py, text),))?,
            NodeData::Doctype {
                name,
                public_id,
                system_id,
            } => conv.doctype(name.as_ref(), public_id.as_ref(), system_id.as_ref())?,
            NodeData::Document | NodeData::Fragment => {
                return Err(PyErr::new::<PyRuntimeError, _>(
                    "soup5ever internal error: document or fragment node inside the tree",
                ));
            }
        };

        obj.setattr(a_parent, &frame.parent)?;
        if let Some(prev) = previous.as_ref() {
            obj.setattr(a_prev_el, prev)?;
            prev.setattr(a_next_el, &obj)?;
        }
        if let Some(sibling) = frame.last_sibling.as_ref() {
            obj.setattr(a_prev_sib, sibling)?;
            sibling.setattr(a_next_sib, &obj)?;
        }
        frame.contents.append(&obj)?;
        frame.last_sibling = Some(obj.clone());
        previous = Some(obj.clone());

        if children != NONE {
            let contents = obj.getattr(a_contents)?.cast_into::<PyList>()?;
            stack.push(Frame {
                next_child: children,
                parent: obj,
                contents,
                last_sibling: None,
            });
        }
    }

    if let Some(last) = previous.filter(|last| !last.is(soup)) {
        soup.setattr(intern!(py, "_most_recent_element"), last)?;
    }
    Ok(())
}
