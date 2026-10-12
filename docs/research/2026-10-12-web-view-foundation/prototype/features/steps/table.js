// The step table: one project's steps grouped by milestone, in a treegrid. The view owns its
// focus, selection, collapsed groups, sort and peek; it reports focus and selection to the
// workspace (which tells the context when this pane is active) and reads plan data from the
// store, so another pane on the same project is a second live view, never a copy.

import { DpElement } from "../../engine/element.js";
import { html, nothing } from "../../engine/template.js";
import { computed, effect } from "../../engine/signals.js";
import { adopt, css } from "../../ui/style.js";
import "../../ui/grid.js";
import { contextMenu } from "../../ui/menu.js";
import { statusMark, ownerChip, estimate, relativeTime, progressBar } from "../../ui/marks.js";
import { entityUri } from "../../shell/context.js";
import { contextGroups } from "../../shell/surfaces.js";
import { report, openTab } from "../../shell/workspace.js";
import { steps, milestones, lastWrite, STATUSES, STATUS_LABEL } from "../../data/store.js";
import { stepDetail } from "./detail.js";

const compare = {
  status: (a, b) => STATUSES.indexOf(a.status) - STATUSES.indexOf(b.status),
  id: (a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)),
  title: (a, b) => a.title.localeCompare(b.title),
  owner: (a, b) => (a.owner ?? "~").localeCompare(b.owner ?? "~"),
  estimate: (a, b) => a.estimate - b.estimate,
  updated: (a, b) => b.updated - a.updated,
};

const COLUMNS = [
  { key: "status", label: "", width: "calc(var(--icon) + 2 * var(--pad) + 6px)", sortable: true, render: (r) => (r.kind === "group" ? null : statusMark(r.cells.status, STATUS_LABEL[r.cells.status])) },
  { key: "id", label: "Step", width: "52px", sortable: true, render: (r) => (r.kind === "group" ? null : html`<span class="dim">${r.cells.id}</span>`) },
  { key: "title", label: "Title", width: "minmax(220px, 1fr)", sortable: true, tree: true, render: (r) => (r.kind === "group" ? r.cells.name : r.cells.title) },
  { key: "progress", label: "Progress", width: "110px", render: (r) => (r.kind === "group" ? progressBar(r.cells.done / r.cells.count) : needs(r.cells)) },
  { key: "owner", label: "Owner", width: "100px", sortable: true, render: (r) => (r.kind === "group" ? html`<span class="dim">${r.cells.done}/${r.cells.count} done</span>` : ownerChip(r.cells.owner)) },
  { key: "estimate", label: "Estimate", width: "72px", align: "end", sortable: true, render: (r) => estimate(r.kind === "group" ? r.cells.days : r.cells.estimate) },
  { key: "updated", label: "Updated", width: "68px", align: "end", sortable: true, render: (r) => (r.kind === "group" ? null : html`<span class="mark-num dim">${relativeTime(r.cells.updated)}</span>`) },
];

// The steps a step waits for that are not done yet — the "why can't I start" column.
function needs(step) {
  const open = step.needs.filter((id) => steps.peek().get(id)?.status !== "done");
  return open.length ? html`<span class="dim" title=${`Waits for ${open.join(", ")}`}>needs ${open.join(" ")}</span>` : nothing;
}

class StepsView extends DpElement {
  static shadow = false;
  static props = {
    projectId: { type: String },
    paneId: { type: Number },
    follow: { type: Object, attribute: false }, // unused here; a table never follows
    focusKey: { type: Object, value: null, attribute: false },
    selected: { type: Object, value: new Set(), attribute: false },
    collapsed: { type: Object, value: new Set(), attribute: false },
    sort: { type: Object, value: null, attribute: false },
    peek: { type: Boolean, value: false, attribute: false },
    changed: { type: Object, value: new Set(), attribute: false },
  };

  #rows = computed(() => {
    const out = [];
    const all = [...steps.value.values()].filter((s) => s.projectId === this.projectId);
    const groups = milestones.value.filter((m) => m.projectId === this.projectId).sort((a, b) => a.order - b.order);
    const sections = groups.length ? groups.map((m) => [m, all.filter((s) => s.milestoneId === m.id)]) : [[null, all]];
    for (const [milestone, items] of sections) {
      if (milestone) {
        const done = items.filter((s) => s.status === "done").length;
        out.push({ key: milestone.id, level: 1, kind: "group", expandable: true, expanded: !this.collapsed.has(milestone.id), cells: { name: milestone.name, count: items.length, done, days: items.reduce((n, s) => n + s.estimate, 0) } });
        if (this.collapsed.has(milestone.id)) continue;
      }
      if (this.sort) items.sort((a, b) => compare[this.sort.key](a, b) * (this.sort.dir === "asc" ? 1 : -1));
      for (const step of items) out.push({ key: step.id, level: milestone ? 2 : 1, kind: "step", cells: step });
    }
    return out;
  });

  connected() {
    // Rows someone else changed wash once; what you changed yourself stays still.
    this.stopWatching = effect(() => {
      const write = lastWrite.value;
      if (write && write.writer !== "you") this.changed = new Set(write.ids);
    });
  }
  disconnected() {
    this.stopWatching?.();
  }

  publish() {
    report(this.paneId, {
      focus: this.focusKey && steps.peek().has(this.focusKey) ? entityUri("step", this.focusKey) : null,
      selection: [...this.selected].map((id) => entityUri("step", id)),
    });
  }

  clearSelection() {
    this.selected = new Set();
    this.publish();
  }

  selectAll() {
    this.selected = new Set(this.#rows.peek().filter((r) => r.kind === "step").map((r) => r.key));
    this.publish();
  }

  togglePeek() {
    this.peek = !this.peek;
  }

  focusGrid() {
    this.querySelector("dp-grid")?.focus();
  }

  render() {
    const focused = this.focusKey ? steps.value.get(this.focusKey) : null;
    return html`
      <dp-grid
        aria-label="Steps"
        .columns=${COLUMNS}
        .rows=${this.#rows.value}
        .selected=${this.selected}
        .focusKey=${this.focusKey}
        .sort=${this.sort}
        .changed=${this.changed}
        @dp-focus=${(e) => {
          this.focusKey = e.detail.key;
          this.publish();
        }}
        @dp-select=${(e) => {
          this.selected = e.detail.keys;
          this.publish();
        }}
        @dp-toggle=${(e) => {
          const next = new Set(this.collapsed);
          next.has(e.detail.key) ? next.delete(e.detail.key) : next.add(e.detail.key);
          this.collapsed = next;
        }}
        @dp-sort=${(e) => (this.sort = e.detail)}
        @dp-open=${(e) => steps.peek().has(e.detail.key) && openTab("step", { id: e.detail.key }, { preview: true })}
        @dp-context=${(e) => {
          this.focusKey = e.detail.key;
          if (steps.peek().has(e.detail.key) && !this.selected.has(e.detail.key)) this.selected = new Set([e.detail.key]);
          this.publish();
          if (steps.peek().has(e.detail.key)) queueMicrotask(() => contextMenu(e.detail.event, contextGroups("step")));
        }}
      ></dp-grid>
      ${this.peek && focused ? html`<aside class="steps-peek" aria-label="Peek">${stepDetail(focused, { compact: true })}</aside>` : nothing}
    `;
  }
}
StepsView.define("dp-steps-view");

// The workspace's view object for a "steps" tab: one element, kept for the tab's lifetime.
export function stepsView(params) {
  const el = document.createElement("dp-steps-view");
  el.projectId = params.projectId;
  return {
    element: el,
    render({ paneId }) {
      el.paneId = paneId;
      return el;
    },
    publish: () => el.publish(),
    clearSelection: () => el.clearSelection(),
    selectAll: () => el.selectAll(),
    togglePeek: () => el.togglePeek(),
    focus: () => el.focusGrid(),
  };
}


adopt(css`
  dp-steps-view {
    flex: 1;
    min-width: 0;
    display: flex;
  }
  dp-steps-view dp-grid { flex: 1; min-width: 0; }
  dp-steps-view .steps-peek {
    width: min(380px, 42%);
    flex: none;
    border-left: var(--rule);
    background: var(--bg-raised);
    overflow: auto;
    animation: steps-peek-in var(--dur-small) var(--ease-enter);
  }
  @keyframes steps-peek-in { from { translate: 16px 0; opacity: 0.4; } }
  :root[data-variant="atelier"] dp-steps-view .steps-peek {
    margin: 8px;
    border: 0;
    border-radius: var(--radius-pop);
    box-shadow: var(--shadow);
  }
`);
