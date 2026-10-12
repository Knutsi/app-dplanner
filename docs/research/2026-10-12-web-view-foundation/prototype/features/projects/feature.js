// Projects: the library down the left, and a verb per project to go to it — so a project is
// one click, one palette query ("web view"), or File ▸ Open Project.

import { html, repeat } from "../../engine/template.js";
import { computed } from "../../engine/signals.js";
import { adopt, css } from "../../ui/style.js";
import { glyph } from "../../ui/glyph.js";
import { progressBar } from "../../ui/marks.js";
import { commands } from "../../shell/commands.js";
import { registerDescriber, openTab, activeTab, viewOf, setPanel, leftOpen } from "../../shell/workspace.js";
import { projects, steps } from "../../data/store.js";

const progress = computed(() => {
  const by = new Map();
  for (const step of steps.value.values()) {
    const p = by.get(step.projectId) ?? { done: 0, all: 0, blocked: 0 };
    p.all++;
    if (step.status === "done") p.done++;
    if (step.status === "blocked") p.blocked++;
    by.set(step.projectId, p);
  }
  return by;
});

export const openProject = (project, preview = false) =>
  openTab("steps", { projectId: project.id, title: project.name }, { preview });

function library() {
  const current = activeTab.value?.params?.projectId;
  return html`<nav class="library-nav" aria-label="Projects">
    <h2>Projects</h2>
    <ul>
      ${repeat(projects.value, (p) => p.id, (project) => {
        const stats = progress.value.get(project.id) ?? { done: 0, all: 0, blocked: 0 };
        return html`<li>
          <a
            href=${`#${project.id}`}
            aria-current=${project.id === current ? "page" : "false"}
            @click=${(e) => {
              e.preventDefault();
              openProject(project, true);
              queueMicrotask(() => viewOf(activeTab.peek())?.focus?.());
            }}
            @dblclick=${() => openProject(project)}
          >
            ${glyph("project")}
            <span class="library-name">${project.name}</span>
            ${stats.blocked ? html`<span class="library-blocked" title=${`${stats.blocked} blocked`}>${glyph("stop")}</span>` : null}
            <span class="library-count">${stats.done}/${stats.all}</span>
            <span class="library-bar">${progressBar(stats.all ? stats.done / stats.all : 0)}</span>
          </a>
        </li>`;
      })}
    </ul>
  </nav>`;
}

export function register() {
  setPanel("left", { title: "Projects", render: library });
  registerDescriber("project", (id) => projects.peek().find((p) => p.id === id)?.name ?? id);

  commands.register({
    id: "view.library-nav",
    label: "Projects",
    icon: "project",
    menu: "View",
    group: "panes",
    order: 5,
    keys: ["Ctrl+B"],
    state: () => ({ checked: leftOpen.value }),
    run: () => {
      leftOpen.value = !leftOpen.peek();
    },
  });

  commands.register({
    id: "go.projects",
    label: "Go to Projects",
    icon: "project",
    menu: "Go",
    group: "navigate",
    order: 10,
    keys: ["g p"],
    run: () => {
      leftOpen.value = true;
      queueMicrotask(() => document.querySelector(".library-nav a[aria-current='page'], .library-nav a")?.focus());
    },
  });

  // One verb per project: the palette finds "web view" without a separate search feature.
  for (const project of projects.peek())
    commands.register({
      id: `project.open.${project.id}`,
      label: `Open ${project.name}`,
      icon: "project",
      menu: "File",
      group: "project",
      submenu: "Open Recent",
      run: () => openProject(project),
    });
}

adopt(css`
  .library-nav { padding: 10px 6px; }
  .library-nav h2 {
    margin: 2px 8px 8px;
    font-size: var(--fs-small);
    font-weight: 600;
    color: var(--fg-3);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .library-nav ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 1px; }
  .library-nav a {
    display: grid;
    grid-template-columns: var(--icon) 1fr auto auto;
    grid-template-rows: auto auto;
    align-items: center;
    column-gap: 8px;
    row-gap: 3px;
    padding: 6px 8px;
    border-radius: var(--radius);
    color: var(--fg-2);
    text-decoration: none;
  }
  .library-nav a:hover { background: var(--bg-hover); color: var(--fg); }
  .library-nav a[aria-current="page"] { background: var(--sel-bg); color: var(--sel-fg); }
  .library-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .library-count { font-size: var(--fs-small); color: var(--fg-3); font-variant-numeric: tabular-nums; }
  .library-blocked { color: var(--st-blocked); display: inline-flex; }
  .library-blocked .glyph { width: 12px; height: 12px; }
  .library-bar { grid-column: 2 / -1; }
  .library-bar .mark-bar { width: 100%; }
`);
