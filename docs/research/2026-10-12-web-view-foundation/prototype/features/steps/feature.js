// Steps: the table and the detail views, and every verb that acts on a step. Each verb is
// registered once and shows wherever its fields say — menubar, context menu, toolbar band,
// selection bar, palette, keys — so the feature never builds a button of its own.

import { commands } from "../../shell/commands.js";
import { targets, entityUri } from "../../shell/context.js";
import { registerView, registerDescriber, openTab, activeView } from "../../shell/workspace.js";
import { startTask, wait } from "../../shell/activity.js";
import { toast } from "../../ui/toast.js";
import { STATUS_GLYPH } from "../../ui/marks.js";
import { steps, update, STATUSES, STATUS_LABEL } from "../../data/store.js";
import { stepsView } from "./table.js";
import { stepView } from "./detail.js";
import { stepsTouchView, stepTouchView } from "./touch.js";

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const noStep = { enabled: false, reason: "Select or focus a step first" };
const onSteps = (ctx) => (targets(ctx, "step").length ? {} : noStep);

const STATUS_KEYS = { pending: "s n", "in-progress": "s i", "ready-for-review": "s r", "ready-to-merge": "s m", done: "s d", blocked: "s b" };
const OWNERS = [
  ["claude", "a c"],
  ["codex", "a x"],
  ["knut", "a k"],
];

export function register() {
  registerView("steps", {
    icon: "table",
    title: (p) => p.title ?? "Steps",
    uri: (p) => `app://activity/steps/${p.projectId}`,
    create: stepsView,
    touch: stepsTouchView,
  });
  registerView("step", {
    icon: "step",
    title: (p) => (p.id ? `${p.id} ${steps.peek().get(p.id)?.title ?? ""}` : "Focused step"),
    uri: (p) => (p.id ? entityUri("step", p.id) : "app://activity/step"),
    create: stepView,
    touch: stepTouchView,
  });
  registerDescriber("step", (id) => {
    const step = steps.peek().get(id);
    return step ? `${id} ${step.title}` : id;
  });

  commands.register({
    id: "step.open",
    label: "Open",
    icon: "read",
    menu: "Step",
    group: "edit",
    order: 10,
    keys: ["Enter"],
    for: "step",
    toolbar: "step",
    touch: false, // a tap opens
    state: (ctx) => (targets(ctx, "step").length === 1 ? {} : { enabled: false, reason: "Open works on one step" }),
    run: (ctx) => openTab("step", { id: targets(ctx, "step")[0] }),
  });

  commands.register({
    id: "step.peek",
    label: "Peek",
    icon: "eye",
    menu: "Step",
    group: "edit",
    order: 20,
    keys: ["Space"],
    for: "step",
    toolbar: "step",
    touch: false, // a phone shows the detail itself
    state: (ctx) => ({ ...onSteps(ctx), checked: !!activeView()?.element?.peek }),
    run: () => activeView()?.togglePeek?.(),
  });

  for (const status of STATUSES)
    commands.register({
      id: `step.status.${status}`,
      label: STATUS_LABEL[status],
      icon: STATUS_GLYPH[status],
      menu: "Step",
      group: "status",
      submenu: "Status",
      order: STATUSES.indexOf(status),
      keys: [STATUS_KEYS[status]],
      for: "step",
      toolbar: "status",
      bulk: true,
      state: (ctx) => {
        const ids = targets(ctx, "step");
        if (!ids.length) return noStep;
        return { checked: ids.every((id) => steps.peek().get(id)?.status === status) };
      },
      run: (ctx) => {
        const ids = targets(ctx, "step");
        const undo = update(ids, { status });
        toast(`${plural(ids.length, "step")} set to ${STATUS_LABEL[status]}`, { undo: () => commands.undo() });
        return undo;
      },
    });

  for (const [owner, keys] of OWNERS)
    commands.register({
      id: `step.assign.${owner}`,
      label: owner[0].toUpperCase() + owner.slice(1),
      icon: owner === "knut" ? "person" : "spark",
      menu: "Step",
      group: "status",
      submenu: "Assign To",
      keys: [keys],
      for: "step",
      bulk: true,
      state: (ctx) => {
        const ids = targets(ctx, "step");
        return ids.length ? { checked: ids.every((id) => steps.peek().get(id)?.owner === owner) } : noStep;
      },
      run: (ctx) => update(targets(ctx, "step"), { owner }),
    });

  commands.register({
    id: "step.copy-link",
    label: "Copy Link",
    icon: "link",
    menu: "Step",
    group: "link",
    keys: ["y", "Ctrl+Shift+C"],
    for: "step",
    bulk: true,
    state: (ctx) => {
      const n = targets(ctx, "step").length;
      return n ? { label: n > 1 ? `Copy ${n} Links` : "Copy Link" } : noStep;
    },
    run: (ctx) => {
      const uris = targets(ctx, "step").map((id) => entityUri("step", id));
      navigator.clipboard?.writeText(uris.join("\n")).catch(() => {});
      toast(uris.length === 1 ? `Copied ${uris[0]}` : `Copied ${uris.length} links`);
    },
  });

  // Run Agent: background work on the thing itself. The step turns In Progress at once (your
  // write, no flash); when the agent finishes, *it* writes Ready for Review — another writer,
  // so the row washes once wherever it is shown.
  commands.register({
    id: "step.run-agent",
    label: "Run Agent",
    icon: "play",
    menu: "Step",
    group: "agent",
    keys: ["R"],
    for: "step",
    toolbar: "agent",
    bulk: true,
    state: (ctx) => {
      const ids = targets(ctx, "step");
      if (!ids.length) return noStep;
      const done = ids.filter((id) => steps.peek().get(id)?.status === "done");
      if (done.length === ids.length) return { enabled: false, reason: "These steps are done" };
      return { label: ids.length > 1 ? `Run Agents on ${ids.length} Steps` : "Run Agent" };
    },
    run: (ctx) => {
      const ids = targets(ctx, "step").filter((id) => steps.peek().get(id)?.status !== "done");
      update(ids, { status: "in-progress", owner: "claude" });
      for (const id of ids)
        startTask(`Agent on ${id}`, {
          subject: entityUri("step", id),
          steps: [
            async (progress) => {
              for (let i = 1; i <= 10; i++) await wait(280 + Math.random() * 200).then(() => progress(i / 10));
            },
            async () => update([id], { status: "ready-for-review" }, "claude"),
          ],
        });
    },
  });
}
