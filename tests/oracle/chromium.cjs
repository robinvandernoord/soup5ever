// Parse HTML documents with Chromium's DOMParser (scripting disabled, like
// soup5ever and html5lib) and print each tree in html5lib-tests format.
//
//   NODE_PATH=<global node_modules> node tests/oracle/chromium.cjs < in.json > out.json
//
// Input: a JSON array of strings. Output: a JSON array of strings.
// Used by tests/oracle/classify.py as an independent reference when
// triaging html5lib/html5ever differences; not needed for the test suite.
const { chromium } = require("playwright");

(async () => {
const input = JSON.parse(await new Promise((resolve) => {
  let data = "";
  process.stdin.on("data", (c) => (data += c));
  process.stdin.on("end", () => resolve(data));
}));

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || undefined,
});
const page = await browser.newPage();
const output = await page.evaluate((docs) => {
  const NS = {
    "http://www.w3.org/1999/xhtml": "",
    "http://www.w3.org/2000/svg": "svg ",
    "http://www.w3.org/1998/Math/MathML": "math ",
  };
  const ATTR_NS = {
    "http://www.w3.org/1999/xlink": "xlink ",
    "http://www.w3.org/XML/1998/namespace": "xml ",
    "http://www.w3.org/2000/xmlns/": "xmlns ",
  };
  function walk(node, depth, lines) {
    const indent = "| " + "  ".repeat(depth);
    switch (node.nodeType) {
      case Node.DOCUMENT_TYPE_NODE: {
        const ids = node.publicId || node.systemId;
        lines.push(indent + "<!DOCTYPE " + node.name +
          (ids ? ` "${node.publicId}" "${node.systemId}"` : "") + ">");
        return;
      }
      case Node.COMMENT_NODE:
        lines.push(indent + "<!-- " + node.data + " -->");
        return;
      case Node.TEXT_NODE:
        lines.push(indent + '"' + node.data + '"');
        return;
      case Node.ELEMENT_NODE: {
        lines.push(indent + "<" + (NS[node.namespaceURI] ?? node.namespaceURI + " ") + node.localName + ">");
        const attrs = [...node.attributes].map((a) =>
          [(a.namespaceURI ? (ATTR_NS[a.namespaceURI] ?? "") + a.localName : a.name), a.value]);
        attrs.sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
        for (const [k, v] of attrs) lines.push("| " + "  ".repeat(depth + 1) + `${k}="${v}"`);
        let children = node.childNodes;
        let childDepth = depth + 1;
        if (node.localName === "template" && node.namespaceURI === "http://www.w3.org/1999/xhtml") {
          lines.push("| " + "  ".repeat(depth + 1) + "content");
          children = node.content.childNodes;
          childDepth += 1;
        }
        for (const c of children) walk(c, childDepth, lines);
      }
    }
  }
  return docs.map((markup) => {
    const doc = new DOMParser().parseFromString(markup, "text/html");
    const lines = [];
    for (const c of doc.childNodes) walk(c, 0, lines);
    return lines.join("\n");
  });
}, input);
await browser.close();
process.stdout.write(JSON.stringify(output));
})();
