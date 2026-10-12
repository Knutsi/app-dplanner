// The base element: declared properties held in signals, and one render that reruns when
// anything it read changes — coalesced into a microtask, so ten writes cost one render.

import { effect, signal } from "./signals.js";
import { render, unrender } from "./template.js";

const SIGNALS = Symbol("signals");

const fromAttribute = {
  [String.name]: (v) => v,
  [Number.name]: (v) => (v === null ? null : Number(v)),
  [Boolean.name]: (v) => v !== null,
};

export class DpElement extends HTMLElement {
  // name -> { type: String | Number | Boolean | Object, value, attribute: true | "name" | false, reflect }
  static props = {};
  static styles = []; // CSSStyleSheets from css``
  static shadow = true; // false renders into the element itself, inside the page's styles

  static define(tag) {
    const attributes = new Map();
    for (const [name, spec] of Object.entries(this.props)) {
      const attr = spec.attribute === false || spec.type === Object ? null : (typeof spec.attribute === "string" ? spec.attribute : name.toLowerCase());
      if (attr) attributes.set(attr, name);
      Object.defineProperty(this.prototype, name, {
        get() {
          return this[SIGNALS].get(name).value;
        },
        set(value) {
          this[SIGNALS].get(name).value = value;
          if (spec.reflect && attr) reflect(this, attr, spec.type, value);
        },
        configurable: true,
      });
    }
    this.attributeToProp = attributes;
    Object.defineProperty(this, "observedAttributes", { value: [...attributes.keys()] });
    customElements.define(tag, this);
    return this;
  }

  #dispose = null;
  #queued = false;

  constructor() {
    super();
    this[SIGNALS] = new Map();
    for (const [name, spec] of Object.entries(this.constructor.props)) {
      // A property set before the element upgraded lives on the instance; adopt it.
      const early = Object.hasOwn(this, name) ? this[name] : spec.value;
      delete this[name];
      this[SIGNALS].set(name, signal(early));
    }
  }

  get renderRoot() {
    if (!this.constructor.shadow) return this;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open", delegatesFocus: this.constructor.delegatesFocus ?? false });
      this.shadowRoot.adoptedStyleSheets = [this.constructor.styles].flat();
    }
    return this.shadowRoot;
  }

  connectedCallback() {
    for (const name of Object.keys(this.constructor.props))
      if (Object.hasOwn(this, name)) console.error(`${this.localName}: a class field "${name}" hides the declared property, so it will not re-render`);
    if (this.#dispose) return;
    this.#dispose = effect(() => render(this.render(), this.renderRoot, { host: this }), {
      schedule: (run) => {
        if (this.#queued) return;
        this.#queued = true;
        queueMicrotask(() => {
          this.#queued = false;
          guard(this);
          run();
          this.updated?.();
        });
      },
    });
    this.updated?.();
    this.connected?.();
  }

  // Leaving the document tears the render down, so nothing keeps writing into detached DOM;
  // coming back renders afresh. A keyed move uses moveBefore, which calls neither.
  disconnectedCallback() {
    this.#dispose?.();
    this.#dispose = null;
    unrender(this.renderRoot);
    this.disconnected?.();
  }

  connectedMoveCallback() {}

  attributeChangedCallback(attr, _old, value) {
    const name = this.constructor.attributeToProp.get(attr);
    const spec = this.constructor.props[name];
    const next = fromAttribute[spec.type?.name ?? "String"](value);
    if (!Object.is(this[SIGNALS].get(name).peek(), next)) this[SIGNALS].get(name).value = next;
  }

  // Resolves after the queued render, for tests and for code that measures the result.
  get updateComplete() {
    return new Promise((resolve) => queueMicrotask(() => queueMicrotask(resolve)));
  }

  emit(type, detail, options = {}) {
    return this.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true, cancelable: true, ...options }));
  }

  render() {
    return null;
  }
}

// A render that writes what it reads re-queues itself forever inside one task, and the page
// freezes with no error. Count renders per element until the page next yields; past a number
// no real update needs, stop and name the element.
const LOOP_LIMIT = 200;
let counts = null;
function guard(element) {
  if (!counts) {
    counts = new Map();
    setTimeout(() => (counts = null));
  }
  const n = (counts.get(element) ?? 0) + 1;
  counts.set(element, n);
  if (n > LOOP_LIMIT) throw new Error(`${element.localName} rendered ${LOOP_LIMIT} times without the page yielding: its render writes a signal it reads`);
}

function reflect(element, attr, type, value) {
  if (type === Boolean) element.toggleAttribute(attr, Boolean(value));
  else if (value === null || value === undefined) element.removeAttribute(attr);
  else if (element.getAttribute(attr) !== String(value)) element.setAttribute(attr, String(value));
}
