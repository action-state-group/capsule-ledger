// SPDX-License-Identifier: Apache-2.0
//
// Node harness for the base-viewer plug-in seam + the tau2 /
// conversation_exchange domain module. It extracts the ACTUAL inline <script>
// blocks from a real `render_base_viewer_html` output (the base
// capsule_viewer.js, then the conversation_exchange_card.js module) and runs
// them in file order via vm.runInThisContext -- exactly as a browser parsing
// top-to-bottom would -- against a minimal DOM shim and a network hard-block.
//
// It proves, offline and with no reimplementation:
//   1. the SEAM registers + dispatches: the base's CapsuleViewer.register got a
//      "conversation_exchange" renderer, and boot() dispatched each record to it
//      keyed on asg_payload.event;
//   2. the tau2 MODULE renders the fields: friendly model, gen-params line,
//      in/out token split, api-served marker all land in the card DOM;
//   3. a forged CO-CARRIED value is re-derived: when the co-carried record is
//      tampered (a digest flipped) the base's in-browser recompute yields a
//      capsule_id MISMATCH -- the tamper is caught, not trusted.
//
// Usage: node js_harness_base_viewer_seam.mjs <rendered-html> <expect-json>
import { readFileSync } from "node:fs";
import vm from "node:vm";

const htmlPath = process.argv[2];
const expectPath = process.argv[3];
const expect = JSON.parse(readFileSync(expectPath, "utf8"));

const html = readFileSync(htmlPath, "utf8").replace(/<!--[\s\S]*?-->/g, "");

// ---- extract inline scripts (must be no <script src=...>) -----------------
const scriptTagRe = /<script([^>]*)>([\s\S]*?)<\/script>/g;
const scripts = [];
let m;
while ((m = scriptTagRe.exec(html)) !== null) {
  if (/\bsrc\s*=/.test(m[1])) {
    throw new Error("base viewer must not have any <script src=...> tag: " + m[1]);
  }
  scripts.push(m[2]);
}
// embed slot + base + one module = 3 inline blocks.
if (scripts.length !== 3) {
  throw new Error("expected 3 inline <script> blocks (embed, base, module), found " + scripts.length);
}

// ---- network hard-block ----------------------------------------------------
function blocked(name) {
  return function (...a) {
    throw new Error("network attempted via " + name + "(" + String(a[0]) + ")");
  };
}
globalThis.fetch = blocked("fetch");
globalThis.XMLHttpRequest = function () { throw new Error("network via XMLHttpRequest"); };
globalThis.WebSocket = function () { throw new Error("network via WebSocket"); };

// ---- minimal DOM shim ------------------------------------------------------
// Enough for the seam to dispatch and the card to build: createElement,
// appendChild, textContent, classList, querySelector by [data-*]/.class,
// <details>/<summary>, and readyState so the base boots synchronously.
function makeClassList(node) {
  return {
    add: (...cs) => cs.forEach((c) => node._classes.add(c)),
    remove: (...cs) => cs.forEach((c) => node._classes.delete(c)),
    contains: (c) => node._classes.has(c),
    toggle: (c) => (node._classes.has(c) ? node._classes.delete(c) : node._classes.add(c)),
  };
}

function makeNode(tag) {
  const node = {
    tagName: (tag || "div").toUpperCase(),
    _classes: new Set(),
    _text: "",
    children: [],
    attributes: {},
    hidden: false,
    style: {},
    dataset: {},
  };
  node.classList = makeClassList(node);
  Object.defineProperty(node, "className", {
    get() { return Array.from(node._classes).join(" "); },
    set(v) { node._classes = new Set(String(v).split(/\s+/).filter(Boolean)); },
  });
  Object.defineProperty(node, "textContent", {
    get() {
      if (node.children.length) return node.children.map((c) => c.textContent).join("");
      return node._text;
    },
    set(v) { node._text = String(v); node.children = []; },
  });
  node.appendChild = (c) => { node.children.push(c); c.parentNode = node; return c; };
  node.setAttribute = (k, v) => { node.attributes[k] = v; };
  node.addEventListener = () => {};
  node.cloneNode = () => cloneNode(node);
  // querySelector over the subtree: supports "[data-x]" and ".class" and "tag".
  node.querySelector = (sel) => queryOne(node, sel);
  node.querySelectorAll = (sel) => queryAll(node, sel);
  return node;
}

function cloneNode(src) {
  const n = makeNode(src.tagName.toLowerCase());
  n._classes = new Set(src._classes);
  n._text = src._text;
  n.attributes = Object.assign({}, src.attributes);
  n.hidden = src.hidden;
  n.children = src.children.map(cloneNode);
  n.children.forEach((c) => (c.parentNode = n));
  return n;
}

function matches(node, sel) {
  sel = sel.trim();
  if (sel.startsWith("[") && sel.endsWith("]")) {
    const inner = sel.slice(1, -1); // data-foo or data-foo=bar
    const eq = inner.indexOf("=");
    const name = eq === -1 ? inner : inner.slice(0, eq);
    return Object.prototype.hasOwnProperty.call(node.attributes, name);
  }
  if (sel.startsWith(".")) return node._classes.has(sel.slice(1));
  if (sel.startsWith("#")) return node.attributes.id === sel.slice(1);
  return node.tagName === sel.toUpperCase();
}

function walk(node, fn) {
  fn(node);
  node.children.forEach((c) => walk(c, fn));
}
function queryOne(root, sel) {
  let found = null;
  walk(root, (n) => { if (!found && n !== root && matches(n, sel)) found = n; });
  return found;
}
function queryAll(root, sel) {
  const out = [];
  walk(root, (n) => { if (n !== root && matches(n, sel)) out.push(n); });
  return out;
}

// The <template> nodes the shell would carry: this base builds every node via
// createElement (no <template>), so the shim needs none. document is the root.
const documentRoot = makeNode("html");
const bodyNodes = {}; // registry of the data-* skeleton hooks
["data-empty", "data-meta", "data-entries", "data-permalink", "data-copy"].forEach((d) => {
  const n = makeNode("div");
  n.setAttribute(d, "");
  bodyNodes[d] = n;
  documentRoot.appendChild(n);
});

globalThis.document = {
  readyState: "complete",
  addEventListener: (ev, fn) => { if (ev === "DOMContentLoaded") fn(); },
  createElement: (tag) => makeNode(tag),
  querySelector: (sel) => (bodyNodes[sel.replace(/^\[|\]$/g, "")] || queryOne(documentRoot, sel)),
  getElementById: () => null,
};

// window is the global; the scripts assign window.CapsuleViewer etc.
globalThis.window = globalThis;
globalThis.location = { href: "file:///demo#", hash: "" };
// navigator is a read-only getter on modern Node globals; define it non-fatally.
if (!("navigator" in globalThis) || typeof globalThis.navigator === "undefined") {
  try { Object.defineProperty(globalThis, "navigator", { value: {}, configurable: true }); } catch (e) {}
}

// ---- run the inline scripts in file order ---------------------------------
for (const src of scripts) {
  vm.runInThisContext(src);
}

// readyState is "complete" in this shim, so the base's IIFE calls boot()
// itself on load (not via a DOMContentLoaded listener). Just let its async
// renderEntry chain settle -- do NOT call boot() again or entries double up.
await new Promise((r) => setTimeout(r, 100));

// ---- assertions ------------------------------------------------------------
const results = { pass: [], fail: [] };
function ok(cond, label) { (cond ? results.pass : results.fail).push(label); }

// 1) the seam registered the conversation_exchange renderer.
const CV = globalThis.window.CapsuleViewer;
ok(!!CV, "base CapsuleViewer exposed");
ok(typeof CV.register === "function", "seam: register() exists");
ok(typeof CV._registry.conversation_exchange === "function",
   "seam: conversation_exchange renderer registered");

// 2) boot dispatched: the entries container has one card per entry, and each
//    card carries the conversation lead + what-ran fields from the MODULE.
const entriesEl = bodyNodes["data-entries"];
const cards = entriesEl.children;
ok(cards.length === expect.n_entries, "seam: dispatched " + cards.length + " card(s) (want " + expect.n_entries + ")");

const dom = documentRoot.textContent;
ok(dom.includes(expect.friendly_model), "module: friendly model shown (" + expect.friendly_model + ")");
ok(dom.includes(expect.gen_params_line), "module: gen-params line (" + expect.gen_params_line + ")");
ok(dom.includes(expect.usage_line), "module: in/out token split (" + expect.usage_line + ")");
ok(dom.includes(expect.api_marker), "module: api-served marker");
ok(dom.includes("conversation_exchange"), "base: kind label shown");
// the tool-call NAME trail rendered
ok(dom.includes(expect.tool_call_name), "module: tool-call name trail (" + expect.tool_call_name + ")");
// the recompute chip stamped by the base said verified (co-carried record intact)
ok(dom.includes("capsule_id verified in your browser"), "base: recompute chip verified for intact record");

// 3) a forged co-carried value is re-derived to a MISMATCH. Recompute the
//    capsule_id of a tampered copy via the base's OWN port and confirm it no
//    longer equals the carried id.
const tampered = JSON.parse(JSON.stringify(expect.sample_record));
tampered.model_attestation.compute_attestation.usage.prompt_tokens += 1; // forge a token count
const rederived = await CV.recomputeCapsuleId(tampered);
ok(rederived !== expect.sample_record.capsule_id,
   "forgery: tampered co-carried usage re-derives a DIFFERENT capsule_id (caught)");
// and the intact record still recomputes to its carried id (parity).
const intact = await CV.recomputeCapsuleId(expect.sample_record);
ok(intact === expect.sample_record.capsule_id,
   "parity: intact record recomputes to its carried capsule_id");

// ---- report ----------------------------------------------------------------
console.log(JSON.stringify(results, null, 2));
if (results.fail.length) {
  process.exit(1);
}
