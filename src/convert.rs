//! Conversion of the finished arena into BeautifulSoup objects.
//!
//! The tree is walked once, in document order.  Each node becomes the same
//! kind of object BeautifulSoup's html5lib builder would create (`Tag` via
//! the soup's element class, `NavigableString`, `Comment`, `Doctype`), and
//! the five linkage attributes BeautifulSoup maintains (`parent`,
//! `previous_element`/`next_element`, `previous_sibling`/`next_sibling`) plus
//! `contents` are set directly.  Because the tree is final, every node is
//! linked exactly once and the linkage is correct by construction; nothing is
//! ever moved after it has been created.

use std::collections::HashMap;

use html5ever::{LocalName, Namespace, QualName};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString, PyTuple};

use crate::sink::{Arena, NodeData, DOCUMENT, NONE};

/// Python-side classes and objects the conversion needs.
pub struct Classes<'py> {
    pub tag: Bound<'py, PyAny>,
    pub string: Bound<'py, PyAny>,
    pub comment: Bound<'py, PyAny>,
    pub doctype: Bound<'py, PyAny>,
    pub namespaced_attribute: Bound<'py, PyAny>,
    pub attribute_dict: Bound<'py, PyAny>,
}

struct Converter<'py, 'a> {
    py: Python<'py>,
    builder: &'a Bound<'py, PyAny>,
    classes: &'a Classes<'py>,
    /// Whether `attribute_dict` stores str values unchanged, so it can be
    /// filled with `PyDict_SetItem` instead of its Python `__setitem__`.
    attribute_dict_is_plain: bool,
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
            let prefix = name.prefix.as_ref().map(|p| PyString::new(py, p));
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
            if self.attribute_dict_is_plain {
                let dict = container.cast::<PyDict>()?;
                for attr in attrs {
                    dict.set_item(self.attr_name(&attr.name)?, PyString::new(py, &attr.value))?;
                }
            } else {
                for attr in attrs {
                    container.set_item(self.attr_name(&attr.name)?, PyString::new(py, &attr.value))?;
                }
            }
            container
        };
        let kwargs = PyDict::new(py);
        if self.store_line_numbers {
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
        name: &Option<html5ever::tendril::StrTendril>,
        public_id: &Option<html5ever::tendril::StrTendril>,
        system_id: &Option<html5ever::tendril::StrTendril>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = self.py;
        let s = |t: &Option<html5ever::tendril::StrTendril>| t.as_ref().map(|t| PyString::new(py, t));
        self.classes.doctype.call_method1(
            intern!(py, "for_name_and_ids"),
            (
                name.as_ref().map_or_else(|| PyString::new(py, ""), |n| PyString::new(py, n)),
                s(public_id),
                s(system_id),
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

/// Populate `soup` (already reset by BeautifulSoup) from `arena`.
pub fn build<'py>(
    py: Python<'py>,
    arena: &Arena,
    soup: &Bound<'py, PyAny>,
    builder: &Bound<'py, PyAny>,
    classes: &Classes<'py>,
    attribute_dict_is_plain: bool,
    store_line_numbers: bool,
) -> PyResult<()> {
    let mut conv = Converter {
        py,
        builder,
        classes,
        attribute_dict_is_plain,
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
    // As with html5lib, the first node's previous_element (and the soup's
    // next_element) stay None.
    let mut previous: Option<Bound<'py, PyAny>> = None;
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
        let obj = match node.data {
            NodeData::Element {
                ref name,
                ref attrs,
                template_contents,
                line,
                pos,
                ..
            } => {
                // Template contents are a separate fragment in the HTML DOM;
                // BeautifulSoup (like html5lib) has no such concept and keeps
                // them as the template's children.
                children = if template_contents != NONE {
                    nodes[template_contents as usize].first_child
                } else {
                    node.first_child
                };
                conv.element(name, attrs, line, pos)?
            }
            NodeData::Text(ref text) => classes.string.call1((PyString::new(py, text),))?,
            NodeData::Comment(ref text) => classes.comment.call1((PyString::new(py, text),))?,
            NodeData::Doctype {
                ref name,
                ref public_id,
                ref system_id,
            } => conv.doctype(name, public_id, system_id)?,
            NodeData::Document | NodeData::Fragment => {
                unreachable!("document/fragment nodes are never children")
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

    if let Some(last) = previous {
        soup.setattr(intern!(py, "_most_recent_element"), last)?;
    }
    Ok(())
}
