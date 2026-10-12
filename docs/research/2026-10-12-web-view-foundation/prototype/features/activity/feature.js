// Activity: the panel that lists background work — agents running, reports building — with
// progress while it runs and a way to the result when it ends.

import { html, repeat, nothing } from "../../engine/template.js";
import { adopt, css } from "../../ui/style.js";
import { glyph } from "../../ui/glyph.js";
import { progressBar, relativeTime } from "../../ui/marks.js";
import { toast } from "../../ui/toast.js";
import { commands } from "../../shell/commands.js";
import { parseUri } from "../../shell/context.js";
import { openTab, describe, setPanel, bottomOpen } from "../../shell/workspace.js";
import { tasks, unseen, onFinish } from "../../shell/activity.js";

function panel() {
  const list = tasks.value;
  return html`<div class="activity-panel">
    <header><h2>Activity</h2><span class="activity-note">${list.filter((t) => t.state === "running").length} running</span></header>
    ${list.length
      ? html`<ul>
          ${repeat(list, (t) => t.id, (task) => {
            const subject = parseUri(task.subject);
            return html`<li class=${`activity-${task.state}`}>
              <span class="activity-icon">${glyph(task.state === "done" ? "check" : task.state === "failed" ? "problem" : "play")}</span>
              <span class="activity-label">${task.label}</span>
              ${subject ? html`<button class="btn ghost" @click=${() => openTab(subject.kind, { id: subject.id }, { preview: true })}>${describe(subject.kind, subject.id)}</button>` : html`<span></span>`}
              <span class="activity-progress">${task.state === "running" ? progressBar(task.progress) : nothing}</span>
              <span class="mark-num activity-age">${relativeTime(task.ended ?? task.started)}</span>
            </li>`;
          })}
        </ul>`
      : html`<p class="activity-empty">Nothing has run yet. Run Agent on a step (R) to start one.</p>`}
  </div>`;
}

export function register() {
  setPanel("bottom", { title: "Activity", render: panel });

  commands.register({
    id: "activity.toggle",
    label: "Activity",
    icon: "gauge",
    menu: "View",
    group: "panes",
    order: 6,
    keys: ["Ctrl+J", "g a"],
    state: () => ({ checked: bottomOpen.value }),
    run: () => {
      bottomOpen.value = !bottomOpen.peek();
      if (bottomOpen.peek()) unseen.value = 0;
    },
  });

  onFinish((task, { notify }) => {
    if (bottomOpen.peek()) unseen.value = 0;
    if (notify) toast(`${task.label} ${task.state === "done" ? "finished" : "failed"}`, { tone: task.state === "done" ? "ok" : "error" });
  });
}

adopt(css`
  .activity-panel { padding: 8px 12px; }
  .activity-panel header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
  .activity-panel h2 { margin: 0; font-size: var(--fs-small); font-weight: 600; color: var(--fg-3); text-transform: uppercase; letter-spacing: 0.06em; }
  .activity-note { color: var(--fg-3); font-size: var(--fs-small); }
  .activity-panel ul { list-style: none; margin: 0; padding: 0; }
  .activity-panel li {
    display: grid;
    grid-template-columns: var(--icon) minmax(120px, 200px) minmax(0, 1fr) 120px 48px;
    align-items: center;
    gap: 10px;
    height: var(--row);
    border-bottom: var(--rule);
  }
  .activity-panel li .btn { justify-self: start; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; height: calc(var(--row) - 4px); }
  .activity-running .activity-icon { color: var(--tone-busy); }
  .activity-done .activity-icon { color: var(--tone-ok); }
  .activity-failed .activity-icon { color: var(--tone-error); }
  .activity-age { color: var(--fg-3); text-align: right; }
  .activity-empty { color: var(--fg-3); margin: 8px 0; }
`);
