// Themes: Omarchy's colors.toml is the one theme format, so a stock Omarchy theme, the
// person's own and DPlanner's house themes are all the same kind of object. Applying one sets
// its raw colours as --om-* on <html>; ui/tokens.css derives every role from those.
//
// "Automatic" follows, in order: the theme a local DPlanner serves at /api/theme (the
// Omarchy theme the desktop is wearing right now, polled like the Qt app polls), else the
// browser's light/dark preference. A page served from CI has no /api/theme and lands on the
// second without asking.

import { signal, computed, effect } from "../engine/signals.js";
import { OMARCHY_THEMES } from "./omarchy-themes.js";

// DPlanner's own DARK and LIGHT (theme/themes.py), written as colors.toml so they travel the
// same road as everyone else's.
export const HOUSE_THEMES = {
  "dplanner-dark": {
    mode: "dark", background: "#14161a", foreground: "#e6e8ec", accent: "#c8a45c", selection: "#33507a",
    red: "#dc6e6e", yellow: "#dcaa5a", green: "#78c88c", blue: "#6ea0dc", magenta: "#9682dc", cyan: "#50b4af",
  },
  "dplanner-light": {
    mode: "light", background: "#f5f4f1", foreground: "#23262b", accent: "#a07c33", selection: "#b3cdee",
    red: "#b8433f", yellow: "#a8741c", green: "#2f8a4c", blue: "#2e5e9e", magenta: "#6c589e", cyan: "#23807a",
  },
};

const KEYS = ["background", "foreground", "accent", "selection", "red", "yellow", "green", "blue", "magenta", "cyan"];
const POLL_MS = 2000;
const STORE = "dp.theme";

export const isLight = (colors) =>
  colors.mode ? colors.mode === "light" : [1, 3, 5].reduce((sum, i) => sum + parseInt(colors.background.slice(i, i + 2), 16), 0) > 382;

// Every theme the picker offers, grouped as the picker shows them.
export function catalogue() {
  return [
    { group: "DPlanner", themes: Object.keys(HOUSE_THEMES).map((name) => ({ id: `house:${name}`, name: name.replace("dplanner-", "DPlanner "), colors: HOUSE_THEMES[name] })) },
    { group: "Omarchy", themes: Object.entries(OMARCHY_THEMES).map(([name, colors]) => ({ id: `omarchy:${name}`, name, colors })) },
  ];
}

const byId = (id) => catalogue().flatMap((g) => g.themes).find((t) => t.id === id) ?? null;

function readChoice() {
  try {
    return localStorage.getItem(STORE) ?? "auto";
  } catch {
    return "auto";
  }
}

export const themeChoice = signal(readChoice()); // "auto" or a catalogue id
const served = signal(null); // { name, colors } from /api/theme, or null when nobody serves one
const prefersLight = signal(matchMedia("(prefers-color-scheme: light)").matches);
matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => (prefersLight.value = e.matches));

// The theme on screen, and where it came from — the status bar and the picker both say so.
export const activeTheme = computed(() => {
  const choice = themeChoice.value;
  if (choice !== "auto") {
    const theme = byId(choice);
    if (theme) return { ...theme, source: "chosen" };
  }
  if (served.value) return { id: "served", name: served.value.name, colors: served.value.colors, source: "desktop" };
  const name = prefersLight.value ? "dplanner-light" : "dplanner-dark";
  return { id: `house:${name}`, name, colors: HOUSE_THEMES[name], source: "browser" };
});

export function chooseTheme(id) {
  themeChoice.value = id;
  try {
    localStorage.setItem(STORE, id);
  } catch {
    /* a private window keeps the choice for this visit only */
  }
}

function apply({ colors }, animate) {
  const write = () => {
    const root = document.documentElement;
    for (const key of KEYS) {
      const value = colors[key] ?? (key === "selection" ? colors.muted : null) ?? (key === "accent" ? colors.blue : null);
      if (value) root.style.setProperty(`--om-${key}`, value);
    }
    root.dataset.mode = isLight(colors) ? "light" : "dark";
  };
  // A theme change is rare and total, so it earns one crossfade — the only screen-wide motion.
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "reduced";
  if (animate && document.startViewTransition && !still) document.startViewTransition(write);
  else write();
}

let etag = null;
async function poll() {
  try {
    const response = await fetch("/api/theme", { headers: etag ? { "If-None-Match": etag } : {} });
    if (response.status === 304) return true;
    if (!response.ok) return false;
    etag = response.headers.get("ETag");
    served.value = await response.json();
    return true;
  } catch {
    return false;
  }
}

// Starts following; returns a function that stops. Polling begins only if a server answered.
export async function startThemes() {
  let first = true;
  const stop = effect(() => {
    const theme = activeTheme.value;
    apply(theme, !first);
    first = false;
  });
  let timer = null;
  if (await poll()) timer = setInterval(() => document.visibilityState === "visible" && poll(), POLL_MS);
  return () => {
    stop();
    clearInterval(timer);
  };
}
