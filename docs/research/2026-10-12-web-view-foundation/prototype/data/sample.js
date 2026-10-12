// Sample data: this research's own follow-up, written as a DPlanner plan would hold it. It is
// an example for the prototype, not a plan anyone has committed to.

const hour = 3600000;
const now = Date.now();

const step = (id, milestoneId, title, status, estimate, owner, extra = {}) => ({
  id,
  projectId: "web-view",
  milestoneId,
  title,
  status,
  estimate,
  owner,
  needs: [],
  updated: now - (Number(id.slice(1)) * 7 % 60) * hour,
  ...extra,
});

export const SAMPLE = {
  projects: [
    { id: "web-view", name: "Web view", repo: "Knutsi/app-dplanner" },
    { id: "playbooks", name: "Playbooks", repo: "Knutsi/app-dplanner" },
    { id: "multiplayer", name: "Multiplayer ladder", repo: "Knutsi/dplanner-plans" },
    { id: "film", name: "Product film", repo: "Knutsi/dplanner-plans" },
  ],
  milestones: [
    { id: "m-engine", projectId: "web-view", name: "Engine", order: 1 },
    { id: "m-design", projectId: "web-view", name: "Design system", order: 2 },
    { id: "m-site", projectId: "web-view", name: "Report site", order: 3 },
  ],
  steps: [
    step("S1", "m-engine", "Signals core with version-pull", "done", 1, "claude"),
    step("S2", "m-engine", "Template holes and the tag scanner", "done", 2, "claude"),
    step("S3", "m-engine", "Keyed repeat that moves only what moved", "ready-to-merge", 1, "codex", { needs: ["S2"] }),
    step("S4", "m-engine", "Base element: props, attributes, one render", "ready-for-review", 1, "claude", { needs: ["S1", "S2"] }),
    step("S5", "m-engine", "Adopt server-rendered HTML without re-rendering", "pending", 3, "knut", { needs: ["S4"] }),
    step("S6", "m-design", "Tokens, roles and three variants", "in-progress", 2, "claude"),
    step("S7", "m-design", "Omarchy theme bridge and /api/theme", "in-progress", 1, "claude", { needs: ["S6"] }),
    step("S8", "m-design", "Menubar and menus with the APG contract", "in-progress", 3, "codex", { needs: ["S6"] }),
    step("S9", "m-design", "Context menu, Shift+F10 and long-press", "pending", 1, "codex", { needs: ["S8"] }),
    step("S10", "m-design", "Selection bar in the toolbar's place", "pending", 1, "claude", { needs: ["S8"] }),
    step("S11", "m-design", "Command palette scoped to the selection", "pending", 2, "claude", { needs: ["S8"] }),
    step("S12", "m-design", "Which-key panel and the ? sheet", "pending", 1, "knut", { needs: ["S11"] }),
    step("S13", "m-design", "Step table as a treegrid", "in-progress", 3, "claude", { needs: ["S6"] }),
    step("S14", "m-design", "Motion tokens and the changed-flash", "ready-for-review", 1, "claude", { needs: ["S6"] }),
    step("S15", "m-site", "Read plan repositories in CI", "blocked", 2, "knut", { needs: ["S5"], reason: "Waits for a deploy key on dplanner-plans" }),
    step("S16", "m-site", "Project overview page", "pending", 2, "claude", { needs: ["S15", "S13"] }),
    step("S17", "m-site", "Step peek and detail pane", "pending", 2, "claude", { needs: ["S13"] }),
    step("S18", "m-site", "Activity feed from the event stream", "pending", 3, "codex", { needs: ["S15"] }),
    step("S19", "m-site", "Touch companion for review and status", "pending", 3, "knut", { needs: ["S10", "S11"] }),
    step("S20", "m-site", "Publish to GitHub Pages", "pending", 1, "claude", { needs: ["S16"] }),
    { id: "P1", projectId: "playbooks", milestoneId: null, title: "Gate on a reviewer's verdict", status: "in-progress", estimate: 2, owner: "claude", needs: [], updated: now - 3 * hour },
    { id: "P2", projectId: "playbooks", milestoneId: null, title: "Loop back on a failed check", status: "pending", estimate: 1, owner: "codex", needs: ["P1"], updated: now - 30 * hour },
  ],
};
