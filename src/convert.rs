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
use pyo3::types::{
    PyAnyMethods, PyDict, PyDictMethods, PyFrozenSet, PyFrozenSetMethods, PyList, PyListMethods,
    PySet, PyString, PyTuple,
};
use pyo3::{Bound, FromPyObject, PyAny, PyErr, PyResult, Python, intern};

use crate::sink::{Arena, DOCUMENT, NONE, Node, NodeData};

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
    /// Set for the `html5ever-experimental` builder when every class and
    /// builder method involved is `BeautifulSoup`'s own (see
    /// `_builder._direct_construction`). Objects are then created without
    /// running `Tag.__init__` or `NavigableString.__new__`; the attributes
    /// those would set are set directly, already holding their final values.
    #[pyo3(item)]
    pub direct: Option<Direct<'py>>,
}

/// What `Tag.__init__` would read from the builder, looked up once.
#[derive(FromPyObject)]
pub struct Direct<'py> {
    #[pyo3(item)]
    pub object_new: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub str_new: Bound<'py, PyAny>,
    /// `name -> (can_be_empty_element, string container class or None,
    /// frozenset of multi-valued attribute names or None)`.
    #[pyo3(item)]
    pub name_info: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub attribute_value_list_class: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub known_xml: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub cdata_list_attributes: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub preserve_whitespace_tags: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub main_content_string_types: Bound<'py, PyAny>,
    #[pyo3(item)]
    pub set_up_substitutions: Bound<'py, PyAny>,
}

/// The per-tag-name part of `Tag.__init__`, cached per name.
struct NameInfo<'py> {
    can_be_empty: Bound<'py, PyAny>,
    string_container: Option<Bound<'py, PyAny>>,
    multi_valued: Option<Bound<'py, PyFrozenSet>>,
}

/// The linkage a new node gets when it is created.
struct Links<'py, 'refs> {
    parent: &'refs Bound<'py, PyAny>,
    previous: Option<&'refs Bound<'py, PyAny>>,
    previous_sibling: Option<&'refs Bound<'py, PyAny>>,
}

/// Python's `str.isspace`, i.e. what `\s` means in BS4's `nonwhitespace_re`
/// (`\S+`) that splits multi-valued attributes. Unlike `char::is_whitespace`
/// it includes U+001C..U+001F.
const fn is_python_space(ch: char) -> bool {
    matches!(
        ch,
        '\t'..='\r'
            | '\x1c'..=' '
            | '\u{85}'
            | '\u{a0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200a}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202f}'
            | '\u{205f}'
            | '\u{3000}'
    )
}

struct Converter<'py, 'refs> {
    py: Python<'py>,
    builder: &'refs Bound<'py, PyAny>,
    classes: &'refs Classes<'py>,
    store_line_numbers: bool,
    local_names: HashMap<LocalName, Bound<'py, PyString>>,
    namespaces: HashMap<Namespace, Bound<'py, PyString>>,
    attr_names: HashMap<QualName, Bound<'py, PyAny>>,
    name_infos: HashMap<LocalName, NameInfo<'py>>,
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

    fn name_info(&mut self, direct: &Direct<'py>, name: &LocalName) -> PyResult<&NameInfo<'py>> {
        if !self.name_infos.contains_key(name) {
            let (can_be_empty, string_container, multi_valued) = direct
                .name_info
                .call1((self.local_name(name),))?
                .extract()?;
            self.name_infos.insert(
                name.clone(),
                NameInfo {
                    can_be_empty,
                    string_container,
                    multi_valued,
                },
            );
        }
        Ok(&self.name_infos[name])
    }

    /// The attribute dict `Tag.__init__` would end up with: `class`-like
    /// attributes split into `attribute_value_list_class` lists, the way
    /// `TreeBuilder._replace_cdata_list_attribute_values` splits them.
    fn direct_attrs(
        &mut self,
        direct: &Direct<'py>,
        attrs: &[html5ever::Attribute],
        multi_valued: Option<&Bound<'py, PyFrozenSet>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = self.py;
        let container = self.classes.attribute_dict.call0()?;
        let dict = container.cast::<PyDict>()?;
        for attr in attrs {
            let key = self.attr_name(&attr.name)?;
            if multi_valued.map_or(Ok(false), |names| names.contains(&key))? {
                let values = PyList::empty(py);
                for value in attr
                    .value
                    .split(is_python_space)
                    .filter(|value| !value.is_empty())
                {
                    values.append(PyString::new(py, value))?;
                }
                dict.set_item(key, direct.attribute_value_list_class.call1((values,))?)?;
            } else {
                dict.set_item(key, PyString::new(py, &attr.value))?;
            }
        }
        Ok(container)
    }

    /// A `Tag` in the state `Tag.__init__` (BS4 4.13-4.15) plus the linkage
    /// in `build` would leave it, with the attributes set once each and in
    /// the same order (so `vars()` and `CPython`'s per-class attribute layout
    /// are unchanged). Returns the tag and its `contents`.
    fn direct_element(
        &mut self,
        direct: &Direct<'py>,
        name: &QualName,
        attrs: &[html5ever::Attribute],
        (line, pos): (u32, i64),
        links: &Links<'py, '_>,
    ) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyList>)> {
        let py = self.py;
        let none = py.None().into_bound(py);
        let py_name = self.local_name(&name.local);
        let py_ns = self.namespace(&name.ns);
        let info = self.name_info(direct, &name.local)?;
        let can_be_empty = info.can_be_empty.clone();
        let interesting_string_types = match &info.string_container {
            // `Tag.__init__` makes a new set for each such tag.
            Some(container) => PySet::new(py, [container])?.into_any(),
            None => direct.main_content_string_types.clone(),
        };
        let multi_valued = info.multi_valued.clone();
        let py_attrs = self.direct_attrs(direct, attrs, multi_valued.as_ref())?;
        let contents = PyList::empty(py);

        let tag = direct.object_new.call1((&self.classes.tag,))?;
        tag.setattr(intern!(py, "parser_class"), &none)?;
        tag.setattr(intern!(py, "name"), &py_name)?;
        tag.setattr(intern!(py, "namespace"), py_ns)?;
        tag.setattr(intern!(py, "_namespaces"), PyDict::new(py))?;
        tag.setattr(intern!(py, "prefix"), &none)?;
        if self.store_line_numbers && line != 0 {
            tag.setattr(intern!(py, "sourceline"), line)?;
            tag.setattr(intern!(py, "sourcepos"), pos)?;
        } else {
            tag.setattr(intern!(py, "sourceline"), &none)?;
            tag.setattr(intern!(py, "sourcepos"), &none)?;
        }
        tag.setattr(
            intern!(py, "attribute_value_list_class"),
            &direct.attribute_value_list_class,
        )?;
        tag.setattr(intern!(py, "attrs"), py_attrs)?;
        tag.setattr(intern!(py, "known_xml"), &direct.known_xml)?;
        tag.setattr(intern!(py, "contents"), &contents)?;
        set_links(py, &tag, links)?;
        tag.setattr(intern!(py, "hidden"), false)?;
        if &*name.local == "meta" {
            direct.set_up_substitutions.call1((&tag,))?;
        }
        tag.setattr(intern!(py, "can_be_empty_element"), can_be_empty)?;
        tag.setattr(
            intern!(py, "cdata_list_attributes"),
            &direct.cdata_list_attributes,
        )?;
        tag.setattr(
            intern!(py, "preserve_whitespace_tags"),
            &direct.preserve_whitespace_tags,
        )?;
        tag.setattr(
            intern!(py, "interesting_string_types"),
            interesting_string_types,
        )?;
        Ok((tag, contents))
    }

    /// The object for `node`, created directly or through its class.
    fn create(
        &mut self,
        nodes: &[Node],
        node: &Node,
        links: &Links<'py, '_>,
    ) -> PyResult<Created<'py>> {
        Ok(match (&node.data, self.classes.direct.as_ref()) {
            (
                NodeData::Element {
                    name,
                    attrs,
                    template_contents,
                    line,
                    pos,
                    ..
                },
                direct,
            ) => {
                // Template contents are a separate fragment in the HTML DOM;
                // BeautifulSoup (like html5lib) has no such concept and keeps
                // them as the template's children.
                let children = if *template_contents == NONE {
                    node.first_child
                } else {
                    nodes[*template_contents as usize].first_child
                };
                match direct {
                    Some(config) => {
                        let (tag, contents) =
                            self.direct_element(config, name, attrs, (*line, *pos), links)?;
                        Created {
                            obj: tag,
                            linked: true,
                            contents: Some(contents),
                            children,
                        }
                    }
                    None => Created {
                        obj: self.element(name, attrs, *line, *pos)?,
                        linked: false,
                        contents: None,
                        children,
                    },
                }
            }
            (NodeData::Text(text), Some(direct)) => Created {
                obj: direct_string(self.py, direct, &self.classes.string, text, links)?,
                linked: true,
                contents: None,
                children: NONE,
            },
            (NodeData::Comment(text), Some(direct)) => Created {
                obj: direct_string(self.py, direct, &self.classes.comment, text, links)?,
                linked: true,
                contents: None,
                children: NONE,
            },
            (NodeData::Text(text), None) => Created {
                obj: self.classes.string.call1((PyString::new(self.py, text),))?,
                linked: false,
                contents: None,
                children: NONE,
            },
            (NodeData::Comment(text), None) => Created {
                obj: self
                    .classes
                    .comment
                    .call1((PyString::new(self.py, text),))?,
                linked: false,
                contents: None,
                children: NONE,
            },
            (
                NodeData::Doctype {
                    name,
                    public_id,
                    system_id,
                },
                _,
            ) => Created {
                obj: self.doctype(name.as_ref(), public_id.as_ref(), system_id.as_ref())?,
                linked: false,
                contents: None,
                children: NONE,
            },
            (NodeData::Document | NodeData::Fragment, _) => {
                return Err(PyErr::new::<PyRuntimeError, _>(
                    "soup5ever internal error: document or fragment node inside the tree",
                ));
            }
        })
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

/// The linkage `PageElement.setup` would set, with the final values for the
/// `previous_*` links (the `next_*` ones are set when the next node exists).
fn set_links<'py>(
    py: Python<'py>,
    obj: &Bound<'py, PyAny>,
    links: &Links<'py, '_>,
) -> PyResult<()> {
    let none = py.None().into_bound(py);
    obj.setattr(intern!(py, "parent"), links.parent)?;
    obj.setattr(
        intern!(py, "previous_element"),
        links.previous.unwrap_or(&none),
    )?;
    obj.setattr(intern!(py, "next_element"), &none)?;
    obj.setattr(intern!(py, "next_sibling"), &none)?;
    obj.setattr(
        intern!(py, "previous_sibling"),
        links.previous_sibling.unwrap_or(&none),
    )
}

/// A `NavigableString` (or `Comment`) as `NavigableString.__new__` would
/// leave it, with its linkage.
fn direct_string<'py>(
    py: Python<'py>,
    direct: &Direct<'py>,
    class: &Bound<'py, PyAny>,
    text: &str,
    links: &Links<'py, '_>,
) -> PyResult<Bound<'py, PyAny>> {
    let string = direct.str_new.call1((class, PyString::new(py, text)))?;
    string.setattr(intern!(py, "hidden"), false)?;
    set_links(py, &string, links)?;
    Ok(string)
}

/// A node's new object, whether it is already linked to its parent and
/// predecessors, and (for elements) its `contents` and first child.
struct Created<'py> {
    obj: Bound<'py, PyAny>,
    linked: bool,
    contents: Option<Bound<'py, PyList>>,
    children: u32,
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
        name_infos: HashMap::new(),
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

        let links = Links {
            parent: &frame.parent,
            previous: previous.as_ref(),
            previous_sibling: frame.last_sibling.as_ref(),
        };
        let Created {
            obj,
            linked,
            contents,
            children,
        } = conv.create(nodes, node, &links)?;

        if !linked {
            obj.setattr(a_parent, links.parent)?;
            if let Some(prev) = links.previous {
                obj.setattr(a_prev_el, prev)?;
            }
            if let Some(sibling) = links.previous_sibling {
                obj.setattr(a_prev_sib, sibling)?;
            }
        }
        if let Some(prev) = links.previous {
            prev.setattr(a_next_el, &obj)?;
        }
        if let Some(sibling) = links.previous_sibling {
            sibling.setattr(a_next_sib, &obj)?;
        }
        frame.contents.append(&obj)?;
        frame.last_sibling = Some(obj.clone());
        previous = Some(obj.clone());

        if children != NONE {
            let child_contents = match contents {
                Some(list) => list,
                None => obj.getattr(a_contents)?.cast_into::<PyList>()?,
            };
            stack.push(Frame {
                next_child: children,
                parent: obj,
                contents: child_contents,
                last_sibling: None,
            });
        }
    }

    if let Some(last) = previous.filter(|last| !last.is(soup)) {
        soup.setattr(intern!(py, "_most_recent_element"), last)?;
    }
    Ok(())
}
