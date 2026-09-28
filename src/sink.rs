//! An arena-backed `html5ever::TreeSink`.
//!
//! html5ever mutates the tree heavily while it parses: foster parenting,
//! the adoption agency algorithm, `reparent_children`, text merging.  Doing
//! those mutations on Python objects would mean a Python call per mutation,
//! so instead the whole tree is built here, in Rust, with `u32` node ids and
//! intrusive doubly linked child lists (every mutation is O(1)).  Once parsing
//! is finished the final tree is converted to BeautifulSoup objects in a single
//! pre-order pass (see `convert.rs`).

use std::borrow::Cow;
use std::cell::{Cell, RefCell};

use html5ever::interface::{ElemName, ElementFlags, NodeOrText, QuirksMode, TreeSink};
use html5ever::tendril::StrTendril;
use html5ever::{Attribute, LocalName, Namespace, QualName};

/// Sentinel for "no node".
pub const NONE: u32 = u32::MAX;

/// The document node always lives at index 0.
pub const DOCUMENT: u32 = 0;

pub enum NodeData {
    Document,
    /// The "template contents" fragment of a `<template>` element.
    Fragment,
    Doctype {
        name: Option<StrTendril>,
        public_id: Option<StrTendril>,
        system_id: Option<StrTendril>,
    },
    Text(StrTendril),
    Comment(StrTendril),
    Element {
        name: QualName,
        attrs: Vec<Attribute>,
        /// Index of the template-contents fragment, or `NONE`.
        template_contents: u32,
        mathml_annotation_xml_integration_point: bool,
        /// Source position (html5lib semantics, see `driver.rs`); line 0
        /// means "no position".
        line: u32,
        pos: i64,
    },
}

pub struct Node {
    pub parent: u32,
    pub first_child: u32,
    pub last_child: u32,
    pub prev_sibling: u32,
    pub next_sibling: u32,
    pub data: NodeData,
}

impl Node {
    fn new(data: NodeData) -> Node {
        Node {
            parent: NONE,
            first_child: NONE,
            last_child: NONE,
            prev_sibling: NONE,
            next_sibling: NONE,
            data,
        }
    }
}

/// The finished tree.
pub struct Arena {
    pub nodes: Vec<Node>,
}

impl Arena {
    pub fn children(&self, id: u32) -> Children<'_> {
        Children {
            arena: self,
            next: self.nodes[id as usize].first_child,
        }
    }
}

pub struct Children<'a> {
    arena: &'a Arena,
    next: u32,
}

impl Iterator for Children<'_> {
    type Item = u32;

    fn next(&mut self) -> Option<u32> {
        if self.next == NONE {
            return None;
        }
        let id = self.next;
        self.next = self.arena.nodes[id as usize].next_sibling;
        Some(id)
    }
}

/// Owned element name handed to the tree builder.
///
/// `TreeSink::elem_name` must return something that borrows from `&self`, but
/// our nodes live behind a `RefCell` which the tree builder may need to
/// mutate while the name is alive.  `QualName` is three interned atoms, so
/// cloning it is cheap and sidesteps the borrow entirely.
#[derive(Debug)]
pub struct Name(QualName);

impl ElemName for Name {
    fn ns(&self) -> &Namespace {
        &self.0.ns
    }

    fn local_name(&self) -> &LocalName {
        &self.0.local
    }
}

/// The DOCTYPE token fields, as `Option`s.
///
/// `TreeSink::append_doctype_to_document` receives empty strings for missing
/// public/system identifiers, which makes `<!DOCTYPE html PUBLIC "">`
/// indistinguishable from `<!DOCTYPE html>`.  BeautifulSoup (and html5lib)
/// keep that distinction, so the tokenizer tap in `driver.rs` records the
/// original token here just before the tree builder sees it.
pub type PendingDoctype = (Option<StrTendril>, Option<StrTendril>, Option<StrTendril>);

pub struct Sink {
    nodes: RefCell<Vec<Node>>,
    /// Position assigned to elements created from now on: (line, pos).
    pub position: Cell<(u32, i64)>,
    /// The most recently created element, until its first tree operation
    /// shows whether it is an adoption agency clone (see `create_element`).
    unsettled: Cell<u32>,
    pub pending_doctype: RefCell<Option<PendingDoctype>>,
}

impl Default for Sink {
    fn default() -> Self {
        Self::new()
    }
}

impl Sink {
    pub fn new() -> Sink {
        let mut nodes = Vec::with_capacity(256);
        nodes.push(Node::new(NodeData::Document));
        Sink {
            nodes: RefCell::new(nodes),
            position: Cell::new((1, -1)),
            unsettled: Cell::new(NONE),
            pending_doctype: RefCell::new(None),
        }
    }

    fn push(&self, data: NodeData) -> u32 {
        let mut nodes = self.nodes.borrow_mut();
        let id = nodes.len() as u32;
        assert!(id != NONE, "document too large");
        nodes.push(Node::new(data));
        id
    }

    fn new_text(&self, text: StrTendril) -> u32 {
        self.push(NodeData::Text(text))
    }

    /// Called by operations that insert `inserted` or give `receiver` new
    /// children, to settle the most recently created element.
    ///
    /// Every element the tree builder creates is inserted into the tree
    /// before anything is put inside it, except the copies of formatting
    /// elements made by the adoption agency algorithm, which first receive
    /// children (`reparent_children`, or `append` of the previous node).
    /// html5lib makes those copies with `cloneNode`, which records no source
    /// position, so they lose theirs here too.
    fn settle(&self, inserted: u32, receiver: u32) {
        let id = self.unsettled.get();
        if id == NONE {
            return;
        }
        if id == receiver {
            if let NodeData::Element { ref mut line, .. } =
                self.nodes.borrow_mut()[id as usize].data
            {
                *line = 0;
            }
            self.unsettled.set(NONE);
        } else if id == inserted {
            self.unsettled.set(NONE);
        }
    }
}

/// Detach `id` from its parent, if it has one.
fn detach(nodes: &mut [Node], id: u32) {
    let (parent, prev, next) = {
        let n = &nodes[id as usize];
        (n.parent, n.prev_sibling, n.next_sibling)
    };
    if parent == NONE {
        return;
    }
    if prev != NONE {
        nodes[prev as usize].next_sibling = next;
    } else {
        nodes[parent as usize].first_child = next;
    }
    if next != NONE {
        nodes[next as usize].prev_sibling = prev;
    } else {
        nodes[parent as usize].last_child = prev;
    }
    let n = &mut nodes[id as usize];
    n.parent = NONE;
    n.prev_sibling = NONE;
    n.next_sibling = NONE;
}

fn append_child(nodes: &mut [Node], parent: u32, child: u32) {
    detach(nodes, child);
    let last = nodes[parent as usize].last_child;
    {
        let c = &mut nodes[child as usize];
        c.parent = parent;
        c.prev_sibling = last;
    }
    if last != NONE {
        nodes[last as usize].next_sibling = child;
    } else {
        nodes[parent as usize].first_child = child;
    }
    nodes[parent as usize].last_child = child;
}

fn insert_before(nodes: &mut [Node], sibling: u32, child: u32) {
    detach(nodes, child);
    let (parent, prev) = {
        let s = &nodes[sibling as usize];
        (s.parent, s.prev_sibling)
    };
    debug_assert!(parent != NONE, "insert_before a node without a parent");
    {
        let c = &mut nodes[child as usize];
        c.parent = parent;
        c.prev_sibling = prev;
        c.next_sibling = sibling;
    }
    nodes[sibling as usize].prev_sibling = child;
    if prev != NONE {
        nodes[prev as usize].next_sibling = child;
    } else {
        nodes[parent as usize].first_child = child;
    }
}

/// If `id` is a text node, append `text` to it and return true.
fn try_merge_text(nodes: &mut [Node], id: u32, text: &StrTendril) -> bool {
    if id == NONE {
        return false;
    }
    if let NodeData::Text(ref mut existing) = nodes[id as usize].data {
        existing.push_tendril(text);
        true
    } else {
        false
    }
}

impl TreeSink for Sink {
    type Handle = u32;
    type Output = Arena;
    type ElemName<'a> = Name;

    fn finish(self) -> Arena {
        Arena {
            nodes: self.nodes.into_inner(),
        }
    }

    // BeautifulSoup has no use for parse errors; ignoring them keeps the
    // tokenizer's fast path (no error string formatting).
    fn parse_error(&self, _msg: Cow<'static, str>) {}

    fn get_document(&self) -> u32 {
        DOCUMENT
    }

    fn elem_name<'a>(&'a self, target: &'a u32) -> Name {
        match self.nodes.borrow()[*target as usize].data {
            NodeData::Element { ref name, .. } => Name(name.clone()),
            _ => panic!("elem_name called on a non-element node"),
        }
    }

    fn create_element(&self, name: QualName, attrs: Vec<Attribute>, flags: ElementFlags) -> u32 {
        let template_contents = if flags.template {
            self.push(NodeData::Fragment)
        } else {
            NONE
        };
        let (line, pos) = self.position.get();
        let id = self.push(NodeData::Element {
            name,
            attrs,
            template_contents,
            mathml_annotation_xml_integration_point: flags.mathml_annotation_xml_integration_point,
            line,
            pos,
        });
        self.unsettled.set(id);
        id
    }

    fn create_comment(&self, text: StrTendril) -> u32 {
        self.push(NodeData::Comment(text))
    }

    fn create_pi(&self, target: StrTendril, data: StrTendril) -> u32 {
        // Only xml5ever creates processing instructions; the HTML tokenizer
        // turns `<?...>` into a bogus comment. Keep a lossless fallback anyway.
        let mut text = StrTendril::from_slice("?");
        text.push_tendril(&target);
        text.push_char(' ');
        text.push_tendril(&data);
        self.push(NodeData::Comment(text))
    }

    fn append(&self, parent: &u32, child: NodeOrText<u32>) {
        match child {
            NodeOrText::AppendNode(node) => {
                self.settle(node, *parent);
                append_child(&mut self.nodes.borrow_mut(), *parent, node);
            }
            NodeOrText::AppendText(text) => {
                let last = self.nodes.borrow()[*parent as usize].last_child;
                if !try_merge_text(&mut self.nodes.borrow_mut(), last, &text) {
                    let t = self.new_text(text);
                    append_child(&mut self.nodes.borrow_mut(), *parent, t);
                }
            }
        }
    }

    fn append_based_on_parent_node(
        &self,
        element: &u32,
        prev_element: &u32,
        child: NodeOrText<u32>,
    ) {
        let has_parent = self.nodes.borrow()[*element as usize].parent != NONE;
        if has_parent {
            self.append_before_sibling(element, child);
        } else {
            self.append(prev_element, child);
        }
    }

    fn append_doctype_to_document(
        &self,
        name: StrTendril,
        public_id: StrTendril,
        system_id: StrTendril,
    ) {
        let (name, public_id, system_id) = match self.pending_doctype.borrow_mut().take() {
            Some(original) => original,
            None => (Some(name), Some(public_id), Some(system_id)),
        };
        let id = self.push(NodeData::Doctype {
            name,
            public_id,
            system_id,
        });
        append_child(&mut self.nodes.borrow_mut(), DOCUMENT, id);
    }

    fn get_template_contents(&self, target: &u32) -> u32 {
        match self.nodes.borrow()[*target as usize].data {
            NodeData::Element {
                template_contents, ..
            } if template_contents != NONE => template_contents,
            _ => panic!("get_template_contents called on a non-template node"),
        }
    }

    fn same_node(&self, x: &u32, y: &u32) -> bool {
        x == y
    }

    fn set_quirks_mode(&self, _mode: QuirksMode) {}

    fn append_before_sibling(&self, sibling: &u32, new_node: NodeOrText<u32>) {
        match new_node {
            NodeOrText::AppendNode(node) => {
                self.settle(node, NONE);
                insert_before(&mut self.nodes.borrow_mut(), *sibling, node);
            }
            NodeOrText::AppendText(text) => {
                let prev = self.nodes.borrow()[*sibling as usize].prev_sibling;
                if !try_merge_text(&mut self.nodes.borrow_mut(), prev, &text) {
                    let t = self.new_text(text);
                    insert_before(&mut self.nodes.borrow_mut(), *sibling, t);
                }
            }
        }
    }

    fn add_attrs_if_missing(&self, target: &u32, new_attrs: Vec<Attribute>) {
        let mut nodes = self.nodes.borrow_mut();
        if let NodeData::Element { ref mut attrs, .. } = nodes[*target as usize].data {
            for attr in new_attrs {
                if !attrs.iter().any(|a| a.name == attr.name) {
                    attrs.push(attr);
                }
            }
        }
    }

    fn remove_from_parent(&self, target: &u32) {
        detach(&mut self.nodes.borrow_mut(), *target);
    }

    fn reparent_children(&self, node: &u32, new_parent: &u32) {
        self.settle(NONE, *new_parent);
        let mut nodes = self.nodes.borrow_mut();
        let mut child = nodes[*node as usize].first_child;
        while child != NONE {
            let next = nodes[child as usize].next_sibling;
            append_child(&mut nodes, *new_parent, child);
            child = next;
        }
    }

    fn is_mathml_annotation_xml_integration_point(&self, handle: &u32) -> bool {
        matches!(
            self.nodes.borrow()[*handle as usize].data,
            NodeData::Element {
                mathml_annotation_xml_integration_point: true,
                ..
            }
        )
    }

    // BeautifulSoup has no shadow DOM: `<template shadowrootmode>` stays an
    // ordinary template element, as it does with html5lib.
    fn allow_declarative_shadow_roots(&self, _intended_parent: &u32) -> bool {
        false
    }
}
