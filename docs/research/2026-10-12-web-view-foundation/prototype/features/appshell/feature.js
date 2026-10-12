// The window's own verbs: tabs and panes, undo, the palette and the key sheet, the look
// (variant, theme, motion) and the single-key setting. DPlanner's modules/appshell, here.

import { commands } from "../../shell/commands.js";
import { singleKeys } from "../../shell/keyboard.js";
import { panes, activePane, activeView, split, closePane, closeTab, reopenTab, toggleFollow, overlays } from "../../shell/workspace.js";
import { toast } from "../../ui/toast.js";
import { VARIANTS, variant, reducedMotion } from "../../ui/look.js";
import { catalogue, chooseTheme, themeChoice, activeTheme } from "../../ui/theme.js";

const onePane = () => (panes.value.length > 1 ? {} : { enabled: false, reason: "There is only one pane" });

export function register() {
  // File
  commands.register({ id: "file.close-tab", label: "Close Tab", icon: "close", menu: "File", group: "window", order: 10, keys: ["Alt+W"], run: () => closeTab() });
  commands.register({
    id: "file.reopen-tab",
    label: "Reopen Closed Tab",
    icon: "restore",
    menu: "File",
    group: "window",
    order: 20,
    keys: ["Alt+Shift+T"],
    run: () => reopenTab() || toast("No closed tab to reopen"),
  });
  commands.register({
    id: "file.new-window",
    label: "New Window",
    icon: "external",
    menu: "File",
    group: "window",
    order: 30,
    run: () => window.open(location.href, "_blank", "noopener"),
  });

  // Edit
  commands.register({
    id: "edit.undo",
    label: "Undo",
    icon: "undo",
    menu: "Edit",
    group: "history",
    order: 10,
    keys: ["Ctrl+Z"],
    toolbar: "history",
    state: () => {
      const last = commands.history.value.at(-1);
      return last ? { label: `Undo ${last.label}` } : { enabled: false, reason: "Nothing to undo" };
    },
    run: () => {
      commands.undo();
    },
  });
  commands.register({
    id: "edit.redo",
    label: "Redo",
    icon: "redo",
    menu: "Edit",
    group: "history",
    order: 20,
    keys: ["Ctrl+Shift+Z", "Ctrl+Y"],
    toolbar: "history",
    state: () => {
      const next = commands.future.value.at(-1);
      return next ? { label: `Redo ${next.label}` } : { enabled: false, reason: "Nothing to redo" };
    },
    run: () => {
      commands.redo();
    },
  });
  commands.register({
    id: "edit.select-all",
    label: "Select All",
    icon: "lasso",
    menu: "Edit",
    group: "select",
    order: 10,
    keys: ["Ctrl+A"],
    state: () => (activeView()?.selectAll ? {} : { enabled: false, reason: "This view has nothing to select" }),
    run: () => activeView().selectAll(),
  });
  commands.register({
    id: "edit.clear-selection",
    label: "Clear Selection",
    icon: "eraser",
    menu: "Edit",
    group: "select",
    order: 20,
    keys: ["Escape"],
    palette: false,
    state: (ctx) => (ctx.selection.length ? {} : { enabled: false, reason: "Nothing is selected" }),
    run: () => activeView()?.clearSelection?.(),
  });

  // View: the palette first, the panes, then the look
  commands.register({
    id: "view.palette",
    label: "Command Palette…",
    icon: "find",
    menu: "View",
    group: "palette",
    keys: ["Ctrl+K", "Ctrl+Shift+P"],
    palette: false,
    run: () => overlays.palette(),
  });
  commands.register({
    id: "view.split",
    label: "Split Right",
    icon: "divide-vertical",
    menu: "View",
    group: "panes",
    order: 20,
    keys: ["Ctrl+\\"],
    toolbar: "panes",
    run: () => split(),
  });
  commands.register({
    id: "view.split-follow",
    label: "Split Right, Following Focus",
    icon: "link",
    menu: "View",
    group: "panes",
    order: 25,
    keys: ["Ctrl+Shift+\\"],
    toolbar: "panes",
    run: () => split({ kind: "step", params: {}, follow: true }),
  });
  commands.register({
    id: "view.follow",
    label: "Follow the Other Pane",
    menu: "View",
    group: "panes",
    order: 30,
    state: () => ({ ...onePane(), checked: !!activePane.value?.follow }),
    run: () => toggleFollow(),
  });
  commands.register({ id: "view.close-pane", label: "Close Pane", menu: "View", group: "panes", order: 40, keys: ["Ctrl+Alt+W"], state: onePane, run: () => closePane() });

  for (const v of VARIANTS)
    commands.register({
      id: `view.variant.${v.id}`,
      label: v.label,
      menu: "View",
      group: "look",
      submenu: "Design",
      state: () => ({ checked: variant.value === v.id }),
      run: () => {
        variant.value = v.id;
      },
    });
  commands.register({
    id: "view.reduce-motion",
    label: "Reduce Motion",
    menu: "View",
    group: "look",
    order: 60,
    state: () => ({ checked: reducedMotion.value }),
    run: () => {
      reducedMotion.value = !reducedMotion.peek();
    },
  });
  commands.register({
    id: "view.single-keys",
    label: "Single-Key Shortcuts",
    menu: "View",
    group: "look",
    order: 70,
    state: () => ({ checked: singleKeys.value }),
    run: () => {
      singleKeys.value = !singleKeys.peek();
    },
  });

  // Themes: Automatic and the house themes in the menu; every theme in the palette, where
  // typing "tokyo" is quicker than scrolling a long submenu.
  commands.register({
    id: "theme.auto",
    label: "Automatic",
    menu: "View",
    group: "theme",
    submenu: "Theme",
    order: 0,
    state: () => ({ checked: themeChoice.value === "auto", label: themeChoice.value === "auto" ? `Automatic — ${activeTheme.value.name}` : "Automatic" }),
    run: () => chooseTheme("auto"),
  });
  for (const group of catalogue())
    for (const theme of group.themes)
      commands.register({
        id: `theme.${theme.id}`,
        label: `Theme: ${theme.name}`,
        icon: "palette",
        menu: group.group === "DPlanner" ? "View" : undefined,
        group: group.group === "DPlanner" ? "theme" : undefined,
        submenu: group.group === "DPlanner" ? "Theme" : undefined,
        order: 10,
        state: () => ({ checked: themeChoice.value === theme.id, label: group.group === "DPlanner" ? theme.name : `Theme: ${theme.name}` }),
        run: () => chooseTheme(theme.id),
      });
  commands.register({
    id: "theme.more",
    label: "More Themes…",
    menu: "View",
    group: "theme",
    submenu: "Theme",
    order: 90,
    palette: false,
    run: () => overlays.palette({ only: "theme.", placeholder: "Choose a theme…" }),
  });

  // Help
  commands.register({
    id: "help.keys",
    label: "Keyboard Shortcuts",
    icon: "info",
    menu: "Help",
    group: "keys",
    keys: ["?", "F1"],
    run: () => overlays.cheatsheet(),
  });
  commands.register({
    id: "help.about",
    label: "About This Prototype",
    menu: "Help",
    group: "about",
    run: () => toast("DPlanner web view — research prototype, 12 October 2026. Tabler Icons (MIT)."),
  });
}
