// The step list and detail for touch. Not the desktop table squeezed: 44 px rows of two lines,
// a tap opens, a long press starts selecting (and from then on a tap toggles), and the verbs
// live in the frame's bottom bar — the same commands the desktop menus show.

import { DpElement } from "../../engine/element.js";
import { html, repeat, nothing } from "../../engine/template.js";
import { adopt, css } from "../../ui/style.js";
import { glyph } from "../../ui/glyph.js";
import { statusMark } from "../../ui/marks.js";
import { entityUri, setFocus, setSelection, context, parseUri } from "../../shell/context.js";
import { steps, milestones, STATUS_LABEL } from "../../data/store.js";
import { stepDetail } from "./detail.js";

const LONG_PRESS_MS = 450;
const SLOP_PX = 8;

class StepsTouch extends DpElement {
  static shadow = false;
  static props = { projectId: { type: String }, open: { type: Object, attribute: false } };
  #press = null;

  get selected() {
    return new Set(context.value.selection.map((u) => parseUri(u)?.id));
  }

  #toggle(id) {
    const next = this.selected;
    next.has(id) ? next.delete(id) : next.add(id);
    setSelection([...next].map((i) => entityUri("step", i)));
  }

  #down(e, id) {
    const timer = setTimeout(() => {
      this.#press = null;
      navigator.vibrate?.(10);
      if (!this.selected.has(id)) this.#toggle(id);
      e.target.closest("li")?.setAttribute("data-pressed", "");
    }, LONG_PRESS_MS);
    this.#press = { id, x: e.clientX, y: e.clientY, timer };
  }

  #move(e) {
    if (this.#press && Math.hypot(e.clientX - this.#press.x, e.clientY - this.#press.y) > SLOP_PX) this.#cancel();
  }

  #cancel() {
    clearTimeout(this.#press?.timer);
    this.#press = null;
  }

  #up(id) {
    if (!this.#press) return; // the long press already acted
    this.#cancel();
    if (this.selected.size) this.#toggle(id);
    else {
      setFocus(entityUri("step", id));
      this.open?.("step", { id });
    }
  }

  render() {
    const selecting = this.selected.size > 0;
    const all = [...steps.value.values()].filter((s) => s.projectId === this.projectId);
    const groups = milestones.value.filter((m) => m.projectId === this.projectId).sort((a, b) => a.order - b.order);
    const sections = groups.length ? groups.map((m) => [m, all.filter((s) => s.milestoneId === m.id)]) : [[null, all]];
    const chosen = this.selected;
    return html`<ul class=${`touch-list${selecting ? " selecting" : ""}`} role="list">
      ${sections.map(
        ([milestone, items]) => html`
          ${milestone ? html`<li class="touch-group">${milestone.name}<span>${items.filter((s) => s.status === "done").length}/${items.length}</span></li>` : nothing}
          ${repeat(items, (s) => s.id, (step) => html`<li
            class="touch-row"
            aria-selected=${chosen.has(step.id) ? "true" : "false"}
            @pointerdown=${(e) => this.#down(e, step.id)}
            @pointermove=${(e) => this.#move(e)}
            @pointerup=${() => this.#up(step.id)}
            @pointercancel=${() => this.#cancel()}
            @contextmenu=${(e) => e.preventDefault()}
          >
            <span class="touch-lead">${selecting ? html`<span class="touch-check">${chosen.has(step.id) ? glyph("check") : nothing}</span>` : statusMark(step.status, STATUS_LABEL[step.status])}</span>
            <span class="touch-text">
              <span class="touch-title">${step.title}</span>
              <span class="touch-meta">${step.id} · ${STATUS_LABEL[step.status]}${step.owner ? ` · ${step.owner}` : ""} · ${step.estimate} d</span>
            </span>
            ${selecting ? nothing : glyph("chevron-right")}
          </li>`)}
        `,
      )}
    </ul>`;
  }
}
StepsTouch.define("dp-steps-touch");

class StepTouch extends DpElement {
  static shadow = false;
  static props = { stepId: { type: String } };
  render() {
    const step = steps.value.get(this.stepId);
    return step ? stepDetail(step) : html`<p class="step-detail-empty">This step is gone.</p>`;
  }
}
StepTouch.define("dp-step-touch");

export function stepsTouchView(params, { open }) {
  const el = document.createElement("dp-steps-touch");
  el.projectId = params.projectId;
  el.open = open;
  return { element: el, title: () => params.title ?? "Steps" };
}

export function stepTouchView(params) {
  const el = document.createElement("dp-step-touch");
  el.stepId = params.id;
  setFocus(entityUri("step", params.id));
  return { element: el, title: () => params.id, actionsFor: "step" };
}

adopt(css`
  .touch-list { list-style: none; margin: 0; padding: 0 0 12px; user-select: none; -webkit-user-select: none; }
  .touch-group {
    position: sticky;
    top: 0;
    z-index: 1;
    display: flex;
    justify-content: space-between;
    padding: 14px 16px 6px;
    background: var(--bg);
    color: var(--fg-3);
    font-size: var(--fs-small);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .touch-row {
    display: grid;
    grid-template-columns: 28px 1fr auto;
    align-items: center;
    gap: 12px;
    min-height: 56px;
    padding: 6px 12px 6px 16px;
    border-bottom: var(--rule);
    color: var(--fg-3);
    transition: background-color var(--dur-micro) linear;
    touch-action: pan-y;
  }
  .touch-row:active { background: var(--bg-hover); }
  .touch-row[aria-selected="true"] { background: var(--sel-bg); }
  .touch-row[data-pressed] { animation: touch-press var(--dur-small) var(--ease-enter); }
  @keyframes touch-press { from { scale: 0.98; } }
  .touch-text { display: grid; gap: 2px; min-width: 0; }
  .touch-title { color: var(--fg); font-size: 15px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .touch-meta { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .touch-check {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    border: 2px solid var(--line-strong);
    color: var(--on-accent);
  }
  .touch-row[aria-selected="true"] .touch-check { background: var(--accent); border-color: var(--accent); }
  .touch-check .glyph { width: 14px; height: 14px; stroke-width: 3; }
  dp-step-touch .step-detail { padding: 16px; }
`);
