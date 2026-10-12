// One step, read: the facts a person asks for — where it stands, who has it, how big it is,
// what it waits for and what waits for it. Shown in a peek beside the table, in its own tab,
// and in a pane that follows another pane's focus.

import { DpElement } from "../../engine/element.js";
import { html, nothing } from "../../engine/template.js";
import { adopt, css } from "../../ui/style.js";
import { statusMark, ownerChip, estimate, relativeTime } from "../../ui/marks.js";
import { entityUri, parseUri } from "../../shell/context.js";
import { openTab } from "../../shell/workspace.js";
import { steps, milestones, STATUS_LABEL } from "../../data/store.js";

const link = (id) => {
  const step = steps.value.get(id);
  return html`<a class="step-detail-link" href=${`#${id}`} @click=${(e) => (e.preventDefault(), openTab("step", { id }, { preview: true }))}>
    ${step ? statusMark(step.status, STATUS_LABEL[step.status]) : nothing}<b>${id}</b> ${step?.title ?? "missing"}</a>`;
};

const ago = (ms) => {
  const age = relativeTime(ms);
  return age === "now" ? "just now" : `${age} ago`;
};

export function stepDetail(step, { compact = false } = {}) {
  const milestone = milestones.value.find((m) => m.id === step.milestoneId);
  const waitedOnBy = [...steps.value.values()].filter((s) => s.needs.includes(step.id)).map((s) => s.id);
  return html`<article class=${`step-detail${compact ? " compact" : ""}`}>
    <header>
      <span class="step-detail-id">${step.id}${milestone ? html` · ${milestone.name}` : nothing}</span>
      <h2>${step.title}</h2>
      <p class=${`step-detail-status st-${step.status}`}>${statusMark(step.status)} ${STATUS_LABEL[step.status]}${step.reason ? html`<span class="step-detail-reason"> — ${step.reason}</span>` : nothing}</p>
    </header>
    <dl>
      <dt>Owner</dt><dd>${ownerChip(step.owner)}</dd>
      <dt>Estimate</dt><dd>${estimate(step.estimate)}</dd>
      <dt>Updated</dt><dd>${ago(step.updated)}</dd>
      <dt>URI</dt><dd><code title="The address menus, links and the CLI share">${entityUri("step", step.id)}</code></dd>
    </dl>
    <section>
      <h3>Waits for</h3>
      ${step.needs.length ? html`<ul>${step.needs.map((id) => html`<li>${link(id)}</li>`)}</ul>` : html`<p class="step-detail-none">Nothing — it can start.</p>`}
    </section>
    <section>
      <h3>Needed by</h3>
      ${waitedOnBy.length ? html`<ul>${waitedOnBy.map((id) => html`<li>${link(id)}</li>`)}</ul>` : html`<p class="step-detail-none">Nothing waits for it.</p>`}
    </section>
  </article>`;
}

class StepPage extends DpElement {
  static shadow = false;
  static props = {
    stepId: { type: String },
    follow: { type: Object, value: undefined, attribute: false }, // a followed URI, or undefined when not following
  };
  render() {
    const following = this.follow !== undefined;
    const id = following ? parseUri(this.follow)?.id : this.stepId;
    const step = id ? steps.value.get(id) : null;
    if (!step) return html`<p class="step-detail-empty">${following ? "Focus a step in the other pane." : "This step is gone."}</p>`;
    return stepDetail(step);
  }
}
StepPage.define("dp-step-page");

export function stepView(params) {
  const el = document.createElement("dp-step-page");
  el.stepId = params.id;
  el.tabIndex = -1;
  return {
    element: el,
    render({ follow }) {
      el.follow = follow;
      return el;
    },
    publish: () => {},
    focus: () => el.focus(),
  };
}

adopt(css`
  dp-step-page { flex: 1; overflow: auto; }
  .step-detail { padding: 16px 20px 24px; max-width: 72ch; display: grid; gap: 16px; }
  .step-detail.compact { padding: 12px 14px; gap: 12px; }
  .step-detail header { display: grid; gap: 4px; }
  .step-detail-id { color: var(--fg-3); font-size: var(--fs-small); font-family: var(--font-mono); }
  .step-detail h2 {
    margin: 0;
    font: var(--title-weight) var(--fs-title) / 1.25 var(--font-title);
    text-wrap: balance;
  }
  :root[data-variant="atelier"] .step-detail h2 { font-size: calc(var(--fs-title) * 1.25); }
  .step-detail-status { margin: 0; display: flex; align-items: center; gap: 6px; color: var(--fg-2); }
  .step-detail-reason { color: var(--fg-3); }
  .step-detail dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; align-items: center; }
  .step-detail dt { color: var(--fg-3); font-size: var(--fs-small); }
  .step-detail dd { margin: 0; min-width: 0; }
  .step-detail code { font: var(--fs-small) var(--font-mono); color: var(--fg-2); overflow-wrap: anywhere; }
  .step-detail h3 {
    margin: 0 0 6px;
    font-size: var(--fs-small);
    font-weight: 600;
    color: var(--fg-3);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .step-detail ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
  .step-detail-link {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 6px;
    margin-inline: -6px;
    border-radius: var(--radius);
    color: var(--fg);
    text-decoration: none;
  }
  .step-detail-link:hover { background: var(--bg-hover); }
  .step-detail-link b { font: 500 var(--fs-small) var(--font-mono); color: var(--fg-2); }
  .step-detail-none, .step-detail-empty { margin: 0; color: var(--fg-3); }
  .step-detail-empty { padding: 24px; }
`);
