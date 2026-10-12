import { signal, computed, effect, batch, untracked } from "../engine/signals.js";
import { html, svg, render, repeat, nothing, unrender } from "../engine/template.js";
import { DpElement } from "../engine/element.js";

const results = [];
const test = async (name, fn) => {
  try {
    await fn();
    results.push(`ok   ${name}`);
  } catch (e) {
    results.push(`FAIL ${name}: ${e.message}`);
  }
};
const eq = (a, b, what = "") => {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${what} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
};
const box = () => document.body.appendChild(document.createElement("div"));
const tick = () => new Promise((r) => setTimeout(r, 0));
const mutations = async (target, fn) => {
  const seen = [];
  const mo = new MutationObserver((list) => seen.push(...list));
  mo.observe(target, { childList: true, subtree: true });
  fn();
  await Promise.resolve();
  seen.push(...mo.takeRecords());
  mo.disconnect();
  return seen.reduce((n, r) => n + r.addedNodes.length, 0);
};

// ------------------------------------------------------------------ signals

await test("effect reruns on change, not on an equal write", () => {
  const s = signal(1);
  let runs = 0;
  effect(() => (s.value, runs++));
  s.value = 1;
  s.value = 2;
  eq(runs, 2);
});

await test("diamond is glitch-free and recomputes once", () => {
  const a = signal(1);
  const b = computed(() => a.value * 2);
  const c = computed(() => a.value * 3);
  let seen = [];
  let dRuns = 0;
  const d = computed(() => (dRuns++, b.value + c.value));
  effect(() => seen.push(d.value));
  a.value = 2;
  eq(seen, [5, 10]);
  eq(dRuns, 2);
});

await test("a computed whose result holds stops the wave", () => {
  const n = signal(3);
  const odd = computed(() => n.value % 2 === 1);
  let runs = 0;
  effect(() => (odd.value, runs++));
  n.value = 5;
  eq(runs, 1);
  n.value = 6;
  eq(runs, 2);
});

await test("batch coalesces writes into one run", () => {
  const a = signal(1);
  const b = signal(1);
  let runs = 0;
  effect(() => (a.value + b.value, runs++));
  batch(() => {
    a.value = 2;
    b.value = 2;
  });
  eq(runs, 2);
});

await test("dynamic dependencies are dropped", () => {
  const flag = signal(true);
  const a = signal(0);
  const b = signal(0);
  let runs = 0;
  effect(() => (flag.value ? a.value : b.value, runs++));
  flag.value = false;
  a.value = 1; // no longer read
  eq(runs, 2);
  b.value = 1;
  eq(runs, 3);
});

await test("dispose stops an effect and runs its cleanup", () => {
  const a = signal(0);
  let cleaned = 0;
  let runs = 0;
  const stop = effect(() => {
    a.value;
    runs++;
    return () => cleaned++;
  });
  a.value = 1;
  stop();
  a.value = 2;
  eq([runs, cleaned], [2, 2]);
});

await test("an effect may write a signal another effect reads", () => {
  const a = signal(1);
  const doubled = signal(0);
  const seen = [];
  effect(() => (doubled.value = a.value * 2));
  effect(() => seen.push(doubled.value));
  a.value = 5;
  eq(seen, [2, 10]);
});

await test("untracked reads do not subscribe", () => {
  const a = signal(0);
  let runs = 0;
  effect(() => (untracked(() => a.value), runs++));
  a.value = 1;
  eq(runs, 1);
});

// ------------------------------------------------------------------ templates

await test("text hole updates the same Text node", () => {
  const el = box();
  const t = (v) => html`<p>Hello ${v}!</p>`;
  render(t("a"), el);
  const node = el.querySelector("p").childNodes[1].nextSibling;
  render(t("b"), el);
  eq(el.querySelector("p").textContent, "Hello b!");
  if (el.querySelector("p").childNodes[1].nextSibling !== node) throw new Error("text node replaced");
});

await test("markup in a value stays text", () => {
  const el = box();
  render(html`<p>${"<img src=x onerror=alert(1)>"}</p>`, el);
  eq(el.querySelector("img"), null);
  eq(el.querySelector("p").textContent, "<img src=x onerror=alert(1)>");
});

await test("attributes: whole, interpolated, removed by null", () => {
  const el = box();
  const t = (a, b) => html`<i title=${a} class="row ${b} x" data-k='${b}'></i>`;
  render(t("t", "on"), el);
  const i = el.querySelector("i");
  eq([i.title, i.className, i.dataset.k], ["t", "row on x", "on"]);
  render(t(null, "off"), el);
  eq([i.hasAttribute("title"), i.className], [false, "row off x"]);
});

await test("a '>' inside a quoted attribute does not end the tag", () => {
  const el = box();
  render(html`<b title="a > b ${1}" data-x=${2}>z</b>`, el);
  eq([el.querySelector("b").title, el.querySelector("b").dataset.x], ["a > b 1", "2"]);
});

await test("?bool, .prop and @event with the host as this", () => {
  const el = box();
  const host = { clicks: 0 };
  let adds = 0;
  const t = (on, v, handler) => html`<input ?disabled=${on} .value=${v} @click=${handler}>`;
  render(t(true, "x", function () { this.clicks++; }), el, { host });
  const input = el.querySelector("input");
  const add = input.addEventListener;
  input.addEventListener = function (...a) { adds++; return add.apply(this, a); };
  render(t(false, "y", function () { this.clicks += 10; }), el, { host });
  input.click();
  eq([input.disabled, input.value, host.clicks, adds], [false, "y", 10, 0]);
});

await test("a nested template switches and updates in place", () => {
  const el = box();
  const a = (x) => html`<b>${x}</b>`;
  const b = (x) => html`<i>${x}</i>`;
  const outer = (inner) => html`<div>${inner}</div>`;
  render(outer(a(1)), el);
  const first = el.querySelector("b");
  render(outer(a(2)), el);
  if (el.querySelector("b") !== first) throw new Error("instance not reused");
  render(outer(b(3)), el);
  eq(el.querySelector("div").innerHTML.replace(/<!--[^>]*-->/g, ""), "<i>3</i>");
});

await test("false, null and nothing render nothing", () => {
  const el = box();
  for (const v of [false, null, undefined, nothing]) {
    render(html`<p>${v}</p>`, el);
    eq(el.querySelector("p").textContent, "");
  }
});

await test("arrays render in order and shrink", () => {
  const el = box();
  render(html`<ul>${[1, 2, 3].map((n) => html`<li>${n}</li>`)}</ul>`, el);
  render(html`<ul>${[4, 5].map((n) => html`<li>${n}</li>`)}</ul>`, el);
  eq([...el.querySelectorAll("li")].map((li) => li.textContent), ["4", "5"]);
});

await test("repeat keeps nodes by key and a swap moves two rows", async () => {
  const el = box();
  const rows = Array.from({ length: 200 }, (_, i) => ({ id: i }));
  const t = (items) => html`<ul>${repeat(items, (r) => r.id, (r) => html`<li>${r.id}</li>`)}</ul>`;
  render(t(rows), el);
  const li5 = el.querySelectorAll("li")[5];
  const swapped = rows.slice();
  [swapped[1], swapped[198]] = [swapped[198], swapped[1]];
  const added = await mutations(el, () => render(t(swapped), el));
  const texts = [...el.querySelectorAll("li")].map((li) => li.textContent);
  eq([texts[1], texts[198], texts.length], ["198", "1", 200]);
  if (el.querySelectorAll("li")[5] !== li5) throw new Error("row 5 rebuilt");
  if (added > 6) throw new Error(`swap moved ${added} nodes`);
});

await test("repeat: reverse, insert, remove", () => {
  const el = box();
  const t = (items) => html`<ul>${repeat(items, (r) => r, (r) => html`<li>${r}</li>`)}</ul>`;
  const read = () => [...el.querySelectorAll("li")].map((li) => li.textContent).join("");
  render(t(["a", "b", "c", "d"]), el);
  render(t(["d", "c", "b", "a"]), el);
  eq(read(), "dcba");
  render(t(["x", "d", "b", "y", "a"]), el);
  eq(read(), "xdbya");
  render(t([]), el);
  eq(read(), "");
});

await test("a signal in a hole updates alone and unsubscribes when replaced", () => {
  const el = box();
  const count = signal(1);
  let renders = 0;
  const view = (v) => (renders++, html`<p>n=${v}</p>`);
  render(view(count), el);
  count.value = 2;
  eq([el.querySelector("p").textContent, renders], ["n=2", 1]);
  render(view("plain"), el);
  count.value = 3;
  eq(el.querySelector("p").textContent, "n=plain");
  eq(count.subs.size, 0, "subscribers");
});

await test("holes inside table rows and bodies", () => {
  const el = box();
  const rows = [["a", 1], ["b", 2]];
  render(html`<table><tbody>${rows.map(([k, v]) => html`<tr><td>${k}</td><td class=${"n"}>${v}</td></tr>`)}</tbody></table>`, el);
  eq([...el.querySelectorAll("td")].map((td) => td.textContent), ["a", "1", "b", "2"]);
});

await test("a hole inside <textarea> is refused with a remedy", () => {
  let message = "";
  try {
    render(html`<textarea>${"x"}</textarea>`, box());
  } catch (e) {
    message = e.message;
  }
  if (!message.includes(".value")) throw new Error(`no refusal: ${message}`);
});

await test("a hole inside a comment is ignored", () => {
  const el = box();
  render(html`<p><!-- ${"x"} -->${"y"}</p>`, el);
  eq(el.querySelector("p").textContent, "y");
});

await test("svg`` makes SVG-namespace elements", () => {
  const el = box();
  render(html`<svg viewBox="0 0 10 10">${svg`<circle r=${3}></circle>`}</svg>`, el);
  eq(el.querySelector("circle").namespaceURI, "http://www.w3.org/2000/svg");
});

await test("an element hole hands over the element", () => {
  const el = box();
  let got = null;
  render(html`<input ${(e) => (got = e)} type="text">`, el);
  eq(got?.tagName, "INPUT");
});

// ------------------------------------------------------------------ element

class Counter extends DpElement {
  static props = { label: { type: String, value: "n" }, count: { type: Number, value: 0, reflect: true }, items: { type: Object, value: [] } };
  renders = 0;
  render() {
    this.renders++;
    return html`<span>${this.label}=${this.count}</span><b>${this.items.length}</b>`;
  }
}
Counter.define("t-counter");

await test("element: attributes in, reflection out, renders coalesced", async () => {
  const el = box();
  el.innerHTML = `<t-counter label="hits"></t-counter>`;
  const c = el.firstChild;
  eq(c.shadowRoot.querySelector("span").textContent, "hits=0");
  c.count = 1;
  c.count = 2;
  c.items = [1, 2, 3];
  await c.updateComplete;
  eq([c.shadowRoot.textContent, c.getAttribute("count"), c.renders], ["hits=23", "2", 2]);
  c.setAttribute("label", "x");
  await c.updateComplete;
  eq(c.shadowRoot.querySelector("span").textContent, "x=2");
});

await test("element: a property set before upgrade is kept", async () => {
  const early = document.createElement("t-early");
  early.label = "before";
  document.body.append(early);
  class Early extends DpElement {
    static props = { label: { type: String, value: "default" } };
    render() {
      return html`${this.label}`;
    }
  }
  Early.define("t-early");
  eq(early.shadowRoot.textContent, "before");
});

await test("element: a global signal read in render rerenders it", async () => {
  const theme = signal("dark");
  class Themed extends DpElement {
    render() {
      return html`<i>${theme.value}</i>`;
    }
  }
  Themed.define("t-themed");
  const el = box().appendChild(document.createElement("t-themed"));
  theme.value = "light";
  await el.updateComplete;
  eq(el.shadowRoot.textContent, "light");
  el.remove();
  eq(theme.subs.size, 0, "subscribers after disconnect");
});


// ------------------------------------------------------------------ defects found in review

await test("a strings array that is not a template literal is refused (no injection)", () => {
  let refused = false;
  try {
    render(html(['<img src=x onerror="window.PWNED=1">']), box());
  } catch {
    refused = true;
  }
  eq([refused, window.PWNED], [true, undefined]);
});

await test("an SVG <title> takes a hole (tooltips on drawings)", () => {
  const el = box();
  render(html`<svg><rect width="4" height="4"><title>${"S12 · Done"}</title></rect></svg>`, el);
  eq(el.querySelector("title").textContent, "S12 · Done");
  render(svg`<g><title>${"tip"}</title></g>`, el);
  eq(el.querySelector("title").textContent, "tip");
});

await test("per-row computeds let go of their source when the rows go", () => {
  const el = box();
  const sel = signal(1);
  const rows = [1, 2, 3, 4, 5];
  const t = (items) => html`<ul>${repeat(items, (r) => r, (r) => html`<li class=${computed(() => (sel.value === r ? "sel" : ""))}>${r}</li>`)}</ul>`;
  render(t(rows), el);
  eq(sel.subs.size, 5, "while shown");
  render(t([]), el);
  eq(sel.subs.size, 0, "after removal");
});

await test("a detached element stops writing its signal holes", async () => {
  const label = signal("a");
  class Holder extends DpElement {
    render() {
      return html`<i>${label}</i>`;
    }
  }
  Holder.define("t-holder");
  const el = box().appendChild(document.createElement("t-holder"));
  eq(label.subs.size, 1);
  el.remove();
  eq(label.subs.size, 0);
  document.body.append(el);
  label.value = "b";
  eq(el.shadowRoot.textContent, "b");
});

await test("a keyed move keeps focus on the moved row", () => {
  const el = box();
  const t = (items) => html`<div>${repeat(items, (r) => r, (r) => html`<button>${r}</button>`)}</div>`;
  render(t(["a", "b", "c", "d"]), el);
  el.querySelector("button").focus();
  render(t(["b", "c", "d", "a"]), el);
  eq(document.activeElement.textContent, "a");
});

await test("a render whose DOM was replaced from outside fails clearly and recovers", () => {
  const el = box();
  const t = (x) => html`<p>${x}</p>`;
  render(t("one"), el);
  el.replaceChildren();
  let message = "";
  try {
    render(t("two"), el);
  } catch (e) {
    message = e.message;
  }
  if (!message.includes("lost its place")) throw new Error(`unclear: ${message}`);
  unrender(el);
  render(t("three"), el);
  eq(el.textContent, "three");
});

await test("a failing effect does not strand the others", () => {
  const a = signal(0);
  const seen = [];
  const original = window.reportError;
  window.reportError = () => {};
  effect(() => {
    if (a.value === 1) throw new Error("boom");
  });
  effect(() => seen.push(a.value));
  a.value = 1;
  window.reportError = original;
  eq(seen, [0, 1]);
});

await test("a computed that reads itself is reported, not a stack overflow", () => {
  let message = "";
  const loop = computed(() => loop.value + 1);
  try {
    loop.value;
  } catch (e) {
    message = e.message;
  }
  if (!message.includes("read itself")) throw new Error(message);
});

await test("repeat: append and remove-one touch only the ends", async () => {
  const el = box();
  const t = (items) => html`<ul>${repeat(items, (r) => r, (r) => html`<li>${r}</li>`)}</ul>`;
  const rows = Array.from({ length: 50 }, (_, i) => i);
  render(t(rows), el);
  const added = await mutations(el, () => render(t([...rows, 50]), el));
  eq(added, 3, "append adds one row and its two anchors");
  const moved = await mutations(el, () => render(t(rows.filter((r) => r !== 10).concat(50)), el));
  eq(moved, 0, "removing one moves nothing");
});

await test("a parent setting a child's reactive property does not subscribe to it", async () => {
  class Child extends DpElement {
    static props = { items: { type: Object, value: [] } };
    render() {
      return html`${this.items.length}`;
    }
  }
  Child.define("t-child");
  let renders = 0;
  class Parent extends DpElement {
    render() {
      renders++;
      return html`<t-child .items=${[1, 2, 3]}></t-child>`; // a new array every render
    }
  }
  Parent.define("t-parent");
  const el = box().appendChild(document.createElement("t-parent"));
  await el.updateComplete;
  await new Promise((r) => setTimeout(r, 20));
  eq([renders, el.shadowRoot.querySelector("t-child").shadowRoot.textContent], [1, "3"]);
});

window.__results = results;
window.__done = true;
