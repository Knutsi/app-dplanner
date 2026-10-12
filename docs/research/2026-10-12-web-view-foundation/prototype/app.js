// The composition root: the one place features meet. Order matters only where noted.

import { load } from "./data/store.js";
import { SAMPLE } from "./data/sample.js";
import { startThemes } from "./ui/theme.js";
import { commands } from "./shell/commands.js";
import { installKeyboard } from "./shell/keyboard.js";
import { startWorkspace, viewOf, activeTab } from "./shell/workspace.js";
import * as appshell from "./features/appshell/feature.js";
import * as steps from "./features/steps/feature.js";
import * as projects from "./features/projects/feature.js";
import * as activity from "./features/activity/feature.js";

// One bulk load: what a backend-for-frontend would send in one response.
load(SAMPLE);

// Menus list groups in registration order within each group's `order`, so appshell's
// window verbs come first and a feature's verbs follow.
for (const feature of [appshell, steps, projects, activity]) feature.register();

export async function startDesktop() {
  await startThemes();
  installKeyboard(commands);
  startWorkspace("steps", { projectId: "web-view", title: "Web view" });
  document.body.append(document.createElement("dp-app"));
  queueMicrotask(() => viewOf(activeTab.peek())?.focus?.());
}

// The touch UI: the same features and workspace, its own frame.
export async function startTouch() {
  await startThemes();
  startWorkspace("steps", { projectId: "web-view", title: "Web view" });
  document.body.append(document.createElement("dp-touch-app"));
}
