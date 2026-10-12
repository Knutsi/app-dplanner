// Templates: tagged literals rendered into live DOM with only the holes ever touched.
//
// The idea is Lit's (BSD-3-Clause); the code is ours. A template's `strings` array is the
// same object every time the same literal runs, so it is the cache key: the first render
// scans it once, writes an HTML string with a marker at every hole, lets the browser parse
// that into a <template>, and records where each hole landed. Every later render clones the
// template (or reuses the instance already on screen) and hands each hole its new value. A
// value is never parsed as HTML — text becomes a Text node, so markup in data stays data.

import { effect, isSignal, untracked } from "./signals.js";

export const nothing = Symbol("nothing");
const REPEAT = Symbol("repeat");
// The comment and the attribute a hole leaves behind, unique per page load so no author
// text can be mistaken for one.
const MARK = `dp${String(Math.random()).slice(2, 8)}$`;

class TemplateResult {
  constructor(strings, values, svg) {
    this.strings = strings;
    this.values = values;
    this.svg = svg;
  }
}

export const html = (strings, ...values) => new TemplateResult(strings, values, false);
export const svg = (strings, ...values) => new TemplateResult(strings, values, true);

// A keyed list: rows keep their DOM (and focus, and running transitions) when they move.
export const repeat = (items, key, template) => ({ [REPEAT]: true, items, key, template });

// ---------------------------------------------------------------- preparing a template

const RAW_TEXT = new Set(["script", "style", "textarea", "title"]);
const cache = new WeakMap();

function prepare(result) {
  let prepared = cache.get(result.strings);
  if (!prepared) {
    // Only a real template literal has `raw`. A strings array built from data would be parsed
    // as markup — the one road to injection — so it is refused outright.
    if (!Array.isArray(result.strings) || !Object.hasOwn(result.strings, "raw")) throw new Error("html`` and svg`` must be used as template tags");
    prepared = compile(result.strings, result.svg);
    cache.set(result.strings, prepared);
  }
  return prepared;
}

// One pass over the static strings with a small HTML tokenizer: just enough state to know,
// at each hole, whether it sits in text, in an attribute value, or bare inside a tag.
function compile(strings, isSvg) {
  const holes = []; // in value order: { kind, owner, name?, statics? }
  let out = "";
  let mode = "text"; // text | tag | comment | raw
  let rawName = "";
  let sub = "between"; // inside a tag: name | between | attrName | afterName | beforeValue | value
  let tagName = "";
  let closing = false;
  let quote = "";
  let attr = null; // { start, name, statics, current, count }
  let elementBound = false;
  let elementCount = 0;
  let childCount = 0;
  let foreign = isSvg ? 1 : 0; // inside <svg>/<math>, <title> and <style> are ordinary elements

  const endAttr = () => {
    if (attr && attr.count) {
      attr.statics.push(attr.current);
      out = out.slice(0, attr.start);
      const prefix = attr.name[0];
      const kind = { ".": "prop", "@": "event", "?": "bool" }[prefix] ?? "attr";
      const name = kind === "attr" ? attr.name : attr.name.slice(1);
      holes.push({ kind, owner: `e${elementCount}`, name, statics: attr.statics });
      elementBound = true;
    }
    attr = null;
    sub = "between";
  };

  const closeTag = () => {
    if (elementBound) out += ` ${MARK}`;
    if (elementBound) elementCount++;
    elementBound = false;
    out += ">";
    const name = tagName.toLowerCase();
    if (name === "svg" || name === "math") foreign += closing ? -1 : 1;
    if (!closing && !foreign && RAW_TEXT.has(name)) {
      mode = "raw";
      rawName = name;
    } else mode = "text";
  };

  for (let i = 0; i < strings.length; i++) {
    const s = strings[i];
    for (let j = 0; j < s.length; j++) {
      const c = s[j];
      if (mode === "text") {
        if (c === "<" && s.startsWith("!--", j + 1)) {
          mode = "comment";
          out += "<!--";
          j += 3;
          continue;
        }
        if (c === "<" && /[a-zA-Z/]/.test(s[j + 1] ?? "")) {
          mode = "tag";
          sub = "name";
          closing = s[j + 1] === "/";
          tagName = "";
          if (closing) {
            out += "</";
            j++;
            continue;
          }
        }
        out += c;
      } else if (mode === "comment") {
        if (c === "-" && s.startsWith("->", j + 1)) {
          mode = "text";
          out += "-->";
          j += 2;
          continue;
        }
        out += c;
      } else if (mode === "raw") {
        if (c === "<" && s.slice(j + 2, j + 2 + rawName.length).toLowerCase() === rawName && s[j + 1] === "/") {
          mode = "text";
          j--; // let the text state read the closing tag
          continue;
        }
        out += c;
      } else {
        // inside a tag
        if (sub === "name") {
          if (/[\s/>]/.test(c)) sub = "between";
          else {
            tagName += c;
            out += c;
            continue;
          }
        }
        if (sub === "attrName") {
          if (c === "=") {
            sub = "beforeValue";
            out += c;
            continue;
          }
          if (/[\s/>]/.test(c)) sub = "afterName";
          else {
            attr.name += c;
            out += c;
            continue;
          }
        }
        if (sub === "afterName") {
          if (/\s/.test(c)) {
            out += c;
            continue;
          }
          if (c === "=") {
            sub = "beforeValue";
            out += c;
            continue;
          }
          endAttr(); // a valueless attribute; fall through to read c afresh
        }
        if (sub === "beforeValue") {
          if (/\s/.test(c)) {
            out += c;
            continue;
          }
          if (c === '"' || c === "'") {
            quote = c;
            sub = "value";
            out += c;
            continue;
          }
          if (c === ">") {
            endAttr();
            closeTag();
            continue;
          }
          quote = "";
          sub = "value"; // unquoted: fall through
        }
        if (sub === "value") {
          if (quote ? c === quote : /[\s>]/.test(c)) {
            if (quote) out += c;
            endAttr();
            if (c === ">") closeTag();
            else if (!quote) out += c;
            continue;
          }
          attr.current += c;
          out += c;
          continue;
        }
        // between attributes
        if (c === ">") closeTag();
        else if (/\s|\//.test(c)) out += c;
        else {
          attr = { start: out.length, name: c, statics: [], current: "", count: 0 };
          sub = "attrName";
          out += c;
        }
      }
    }
    if (i === strings.length - 1) break;

    // the hole after strings[i]
    if (mode === "text") {
      out += `<!----><!--${MARK}-->`; // start and end anchors, cloned rather than created
      holes.push({ kind: "child", owner: `c${childCount++}` });
    } else if (mode === "raw") {
      throw new Error(`A template hole cannot sit inside <${rawName}>: bind .value instead`);
    } else if (mode === "comment") {
      holes.push({ kind: "skip" });
    } else if (sub === "beforeValue" || sub === "value") {
      if (sub === "beforeValue") {
        quote = "";
        sub = "value";
      }
      attr.statics.push(attr.current);
      attr.current = "";
      attr.count++;
    } else if (sub === "name") {
      throw new Error("A template hole cannot be a tag name");
    } else {
      if (sub === "attrName" || sub === "afterName") endAttr();
      holes.push({ kind: "element", owner: `e${elementCount}` });
      elementBound = true;
    }
  }
  if (mode !== "text") throw new Error(`Template ends inside a ${mode}: ${strings.join("${…}")}`);

  const template = document.createElement("template");
  template.innerHTML = isSvg ? `<svg>${out}</svg>` : out;
  if (isSvg) {
    const wrapper = template.content.firstChild;
    template.content.replaceChildren(...wrapper.childNodes);
  }

  // Find the node each owner landed on, by its index in a document-order walk.
  const nodeOf = new Map();
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_COMMENT);
  let elements = 0;
  let children = 0;
  for (let index = 0, node; (node = walker.nextNode()); index++) {
    if (node.nodeType === Node.COMMENT_NODE) {
      if (node.data === MARK) nodeOf.set(`c${children++}`, index);
    } else if (node.hasAttribute(MARK)) nodeOf.set(`e${elements++}`, index);
  }
  for (const hole of holes) if (hole.owner) hole.node = nodeOf.get(hole.owner);
  return { template, holes };
}

// ---------------------------------------------------------------- instances and parts

class TemplateInstance {
  constructor(prepared, host) {
    this.prepared = prepared;
    this.parts = [];
    this.fragment = document.importNode(prepared.template.content, true);
    const walker = document.createTreeWalker(this.fragment, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_COMMENT);
    let index = -1;
    let node = null;
    for (const hole of prepared.holes) {
      if (hole.kind === "skip") {
        this.parts.push(null);
        continue;
      }
      while (index < hole.node) {
        node = walker.nextNode();
        index++;
        if (node.nodeType === Node.ELEMENT_NODE) node.removeAttribute(MARK);
      }
      this.parts.push(makePart(hole, node, host));
    }
  }

  update(values) {
    let v = 0;
    for (const part of this.parts) {
      if (!part) v++;
      else if (part instanceof AttributePart) {
        part.set(values, v);
        v += part.count;
      } else part.set(values[v++]);
    }
  }

  dispose() {
    for (const part of this.parts) part?.dispose();
  }
}

function makePart(hole, node, host) {
  switch (hole.kind) {
    case "child":
      return new ChildPart(node.previousSibling, node, host);
    case "attr":
      return new AttributePart(node, hole.name, hole.statics);
    case "bool":
      return new BooleanPart(node, hole.name);
    case "prop":
      return new PropertyPart(node, hole.name);
    case "event":
      return new EventPart(node, hole.name, host);
    case "element":
      return new ElementPart(node);
  }
}

// A part whose value may be a signal: then it subscribes and updates itself alone, with no
// render of the template around it.
class Part {
  binding = null;
  set(value) {
    if (isSignal(value)) {
      if (this.bound === value) return;
      this.binding?.();
      this.bound = value;
      this.binding = effect(() => this.commit(value.value));
      return;
    }
    if (this.binding) {
      this.binding();
      this.binding = this.bound = null;
    }
    this.commit(value);
  }
  dispose() {
    this.binding?.();
  }
}

class ChildPart extends Part {
  kind = null; // text | template | node | list | repeat
  value = undefined;

  constructor(start, end, host) {
    super();
    this.start = start;
    this.end = end;
    this.host = host;
  }

  commit(value) {
    if (value === this.value && typeof value !== "object") return; // unchanged text: no DOM read
    if (!this.end.parentNode) throw new Error("A template part lost its place: something outside the engine removed the nodes it renders into");
    if (value === null || value === undefined || value === false || value === nothing) {
      if (this.kind) this.clear();
    } else if (typeof value !== "object") this.#text(value);
    else if (value instanceof TemplateResult) this.#template(value);
    else if (value[REPEAT]) this.#repeat(value);
    else if (value instanceof Node) {
      if (this.value === value) return;
      this.clear();
      this.end.before(value);
      this.kind = "node";
    } else if (typeof value[Symbol.iterator] === "function") this.#list(value);
    else this.#text(value);
    this.value = value;
  }

  #text(value) {
    const text = String(value);
    if (this.kind === "text") {
      this.start.nextSibling.data = text;
      return;
    }
    this.clear();
    this.end.before(document.createTextNode(text));
    this.kind = "text";
  }

  #template(result) {
    const prepared = prepare(result);
    if (this.kind === "template" && this.instance.prepared === prepared) return this.instance.update(result.values);
    const instance = new TemplateInstance(prepared, this.host);
    instance.update(result.values);
    this.clear();
    this.end.before(instance.fragment);
    this.instance = instance;
    this.kind = "template";
  }

  #list(items) {
    if (this.kind !== "list") {
      this.clear();
      this.items = [];
      this.kind = "list";
    }
    let i = 0;
    for (const item of items) {
      if (i === this.items.length) this.items.push(ChildPart.detached(this.host, this.end));
      this.items[i++].set(item);
    }
    for (const extra of this.items.splice(i)) extra.remove();
  }

  // Keyed: parts survive by key. Removed ones go, new ones arrive detached, and the rows on
  // the longest increasing run of old positions stay put while everything else moves — so
  // a swap of two rows moves two rows, not everything between them.
  #repeat({ items, key, template }) {
    if (this.kind !== "repeat") {
      this.clear();
      this.keyed = new Map();
      this.order = [];
      this.kind = "repeat";
    }
    const previous = this.keyed;
    const old = this.order;
    const next = new Map();
    const order = []; // a kept part, or the value a new one will take
    const keys = [];
    let i = 0;
    for (const item of items) {
      const k = key(item, i);
      if (next.has(k)) throw new Error(`repeat(): duplicate key ${String(k)}`);
      let part = previous.get(k);
      const value = template(item, i++);
      if (part) {
        previous.delete(k);
        part.set(value);
      } else part = { fresh: value };
      next.set(k, part);
      keys.push(k);
      order.push(part);
    }
    for (const gone of previous.values()) gone.remove();
    // Rows that kept their place at either end stay put without asking (an append, a removal
    // and a selection change are all this); the middle keeps its longest in-order run.
    let head = 0;
    while (head < order.length && head < old.length && order[head] === old[head]) head++;
    let tail = 0;
    while (tail < order.length - head && tail < old.length - head && order.at(-1 - tail) === old.at(-1 - tail)) tail++;
    const oldIndex = new Map();
    for (let j = head; j < old.length - tail; j++) oldIndex.set(old[j], j);
    const middle = order.slice(head, order.length - tail).map((part) => oldIndex.get(part) ?? -1);
    const stays = new Set([...longestIncreasing(middle)].map((j) => j + head));
    let ref = tail ? order[order.length - tail].start : this.end;
    for (let j = order.length - tail - 1; j >= head; j--) {
      let part = order[j];
      if (part.fresh !== undefined) {
        const value = part.fresh;
        part = order[j] = ChildPart.detached(this.host, ref);
        part.set(value);
        next.set(keys[j], part);
      } else if (!stays.has(j)) part.moveBefore(ref);
      ref = part.start;
    }
    this.keyed = next;
    this.order = order;
  }

  static detached(host, before) {
    const start = document.createComment("");
    const end = document.createComment("");
    if (before) before.before(start, end);
    else document.createDocumentFragment().append(start, end);
    return new ChildPart(start, end, host);
  }

  // A state-preserving move where the browser has one (focus, selection, a running
  // transition and an iframe survive it); elsewhere a plain move that restores focus after.
  moveBefore(ref) {
    const parent = ref.parentNode;
    const nodes = [];
    for (let n = this.start; n !== this.end; n = n.nextSibling) nodes.push(n);
    nodes.push(this.end);
    if (parent.moveBefore) {
      for (const node of nodes) parent.moveBefore(node, ref);
      return;
    }
    const focused = document.activeElement;
    const inside = focused && nodes.some((n) => n === focused || n.contains?.(focused));
    for (const node of nodes) parent.insertBefore(node, ref);
    if (inside) focused.focus({ preventScroll: true });
  }

  clear() {
    this.instance?.dispose();
    this.instance = null;
    if (this.items) for (const item of this.items) item.dispose();
    if (this.keyed) for (const part of this.keyed.values()) part.dispose();
    this.items = this.keyed = this.order = null;
    while (this.start.nextSibling && this.start.nextSibling !== this.end) this.start.nextSibling.remove();
    this.kind = null;
    this.value = undefined;
  }

  remove() {
    this.clear();
    this.dispose();
    this.start.remove();
    this.end.remove();
  }

  dispose() {
    super.dispose();
    this.instance?.dispose();
    if (this.items) for (const item of this.items) item.dispose();
    if (this.keyed) for (const part of this.keyed.values()) part.dispose();
  }
}

// Indices (into `seq`) of one longest strictly increasing subsequence, ignoring -1 (new).
function longestIncreasing(seq) {
  const tails = []; // index into seq of the smallest tail of each length
  const prev = new Array(seq.length);
  for (let i = 0; i < seq.length; i++) {
    if (seq[i] < 0) continue;
    let lo = 0;
    let hi = tails.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (seq[tails[mid]] < seq[i]) lo = mid + 1;
      else hi = mid;
    }
    prev[i] = lo > 0 ? tails[lo - 1] : -1;
    tails[lo] = i;
  }
  const keep = new Set();
  for (let i = tails.at(-1) ?? -1; i >= 0; i = prev[i]) keep.add(i);
  return keep;
}

class AttributePart extends Part {
  constructor(element, name, statics) {
    super();
    this.element = element;
    this.name = name;
    this.statics = statics;
    this.count = statics.length - 1;
    this.whole = this.count === 1 && statics[0] === "" && statics[1] === "";
    this.last = undefined;
    this.held = [];
  }
  // An attribute with several holes may mix signals and plain values; one effect joins them.
  set(values, from) {
    if (this.binding && this.held.every((v, i) => v === values[from + i])) return; // the same signals again
    this.binding?.();
    this.binding = null;
    let signals = false;
    for (let i = from; i < from + this.count; i++) signals ||= isSignal(values[i]);
    if (signals) {
      const mine = (this.held = values.slice(from, from + this.count));
      this.binding = effect(() => this.commit(mine.map((v) => (isSignal(v) ? v.value : v)), 0));
    } else this.commit(values, from);
  }
  commit(values, from) {
    const first = values[from];
    let next;
    if (this.whole && (first === null || first === undefined || first === nothing)) next = null;
    else if (this.whole) next = String(first);
    else {
      next = this.statics[0];
      for (let i = 0; i < this.count; i++) next += String(values[from + i] ?? "") + this.statics[i + 1];
    }
    if (next === this.last) return;
    this.last = next;
    if (next === null) this.element.removeAttribute(this.name);
    else this.element.setAttribute(this.name, next);
  }
}

class BooleanPart extends Part {
  constructor(element, name) {
    super();
    this.element = element;
    this.name = name;
  }
  commit(value) {
    this.element.toggleAttribute(this.name, Boolean(value) && value !== nothing);
  }
}

// Compares with what it last committed, never by reading the element: a child's property may
// be a signal, and reading it inside the parent's render would subscribe the parent to its
// own child — every write then re-renders the parent, which writes again.
class PropertyPart extends Part {
  constructor(element, name) {
    super();
    this.element = element;
    this.name = name;
    this.last = PropertyPart.unset;
  }
  static unset = Symbol("unset");
  commit(value) {
    if (Object.is(this.last, value)) return;
    this.last = value;
    this.element[this.name] = value;
  }
}

// One listener per hole for its lifetime; a new handler replaces the old one in place.
class EventPart extends Part {
  constructor(element, name, host) {
    super();
    this.element = element;
    this.name = name;
    this.host = host;
    this.handler = null;
  }
  commit(handler) {
    if (handler && !this.handler) this.element.addEventListener(this.name, this);
    if (!handler && this.handler) this.element.removeEventListener(this.name, this);
    this.handler = handler;
  }
  handleEvent(event) {
    this.handler?.call(this.host ?? this.element, event);
  }
}

// `<input ${(el) => (this.input = el)}>`: hands the element to a callback when it changes.
class ElementPart extends Part {
  constructor(element) {
    super();
    this.element = element;
    this.last = null;
  }
  commit(callback) {
    if (callback === this.last) return;
    this.last = callback;
    if (callback) untracked(() => callback(this.element)); // a ref callback is not part of the render
  }
}

// ---------------------------------------------------------------- entry points

const roots = new WeakMap();

export function render(value, container, { host } = {}) {
  let part = roots.get(container);
  if (!part) {
    part = ChildPart.detached(host, null);
    container.append(part.start, part.end);
    roots.set(container, part);
  }
  part.set(value);
  return part;
}

// Tears a render down: every part disposed (so no signal keeps writing into detached DOM) and
// the container emptied. The element base calls it on disconnect and renders afresh on connect.
export function unrender(container) {
  const part = roots.get(container);
  if (!part) return;
  roots.delete(container);
  part.remove();
}

const sheets = new WeakMap();

// A constructable stylesheet per literal, shared by every instance that adopts it.
export function css(strings, ...values) {
  let sheet = sheets.get(strings);
  if (!sheet) {
    sheet = new CSSStyleSheet();
    sheet.replaceSync(String.raw(strings, ...values));
    sheets.set(strings, sheet);
  }
  return sheet;
}
