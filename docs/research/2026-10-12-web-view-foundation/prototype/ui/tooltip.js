// The one tooltip. Any element with data-tip="Words" (and data-tip-keys="Ctrl+K" for its
// binding) gets it: after 500 ms of hover or on keyboard focus, and at once while "warm" —
// within 400 ms of the last one closing, so a person sweeping a toolbar reads each verb
// without waiting again. It stays while hovered (WCAG 1.4.13), Escape dismisses it, and touch
// never sees it: a finger has no hover, so a touch surface says its words out loud instead.

import { html, nothing, render } from "../engine/template.js";
import { kbd } from "./keys.js";
import { adopt, css } from "./style.js";

const DELAY_MS = 500;
const WARM_MS = 400;
const GRACE_MS = 100;
const GAP_PX = 6;
const EDGE_PX = 4;

let tip = null;
let current = null;
let describedBefore = null;
let showTimer = 0;
let hideTimer = 0;
let warmUntil = 0;

export function tooltips() {
  if (tip) return;
  tip = document.createElement("div");
  tip.className = "dp-tooltip";
  tip.id = "dp-tooltip";
  tip.setAttribute("role", "tooltip");
  tip.popover = "manual";
  document.body.append(tip);

  document.addEventListener("pointerover", (e) => {
    if (e.pointerType === "touch") return;
    if (tip.contains(e.target)) return clearTimeout(hideTimer);
    const target = e.target.closest?.("[data-tip]");
    if (target === current && target) return clearTimeout(hideTimer);
    if (target) schedule(target);
    else leave();
  });
  document.addEventListener("pointerout", (e) => {
    const to = e.relatedTarget;
    if (to && (current?.contains(to) || tip.contains(to))) return;
    if (e.target.closest?.("[data-tip]") || tip.contains(e.target)) leave();
  });
  document.addEventListener("focusin", (e) => {
    const target = e.target.closest?.("[data-tip]");
    if (target?.matches(":focus-visible")) schedule(target);
  });
  document.addEventListener("focusout", () => hide());
  document.addEventListener("pointerdown", () => hide(), true);
  window.addEventListener("scroll", () => hide(), true);
  // Escape takes the tooltip away first — one level at a time — except inside a menu, where
  // the same Escape closes the menu and the tooltip with it.
  window.addEventListener(
    "keydown",
    (e) => {
      if (e.key !== "Escape" || !current) return;
      const inMenu = current.closest('[role="menu"]');
      hide();
      if (!inMenu) {
        e.preventDefault();
        e.stopPropagation();
      }
    },
    true,
  );
}

function schedule(target) {
  clearTimeout(showTimer);
  clearTimeout(hideTimer);
  if (current && current !== target) hide();
  const delay = performance.now() < warmUntil ? 0 : DELAY_MS;
  showTimer = setTimeout(() => show(target), delay);
}

function leave() {
  clearTimeout(showTimer);
  clearTimeout(hideTimer);
  hideTimer = setTimeout(hide, GRACE_MS);
}

function show(target) {
  if (!target.isConnected || !target.dataset.tip) return;
  const keys = target.dataset.tipKeys;
  render(html`<span>${target.dataset.tip}</span>${keys ? kbd(keys, { plain: true }) : nothing}`, tip);
  current = target;
  describedBefore = target.getAttribute("aria-describedby");
  target.setAttribute("aria-describedby", tip.id);
  if (!tip.matches(":popover-open")) tip.showPopover();
  place(target.getBoundingClientRect());
}

function place(r) {
  const w = tip.offsetWidth;
  const h = tip.offsetHeight;
  let y = r.bottom + GAP_PX;
  if (y + h > innerHeight - EDGE_PX) y = r.top - h - GAP_PX;
  const x = Math.min(Math.max(r.left + r.width / 2 - w / 2, EDGE_PX), innerWidth - w - EDGE_PX);
  tip.style.left = `${x}px`;
  tip.style.top = `${Math.max(y, EDGE_PX)}px`;
}

function hide() {
  clearTimeout(showTimer);
  clearTimeout(hideTimer);
  if (!current) return;
  if (describedBefore === null) current.removeAttribute("aria-describedby");
  else current.setAttribute("aria-describedby", describedBefore);
  current = null;
  if (tip.matches(":popover-open")) tip.hidePopover();
  warmUntil = performance.now() + WARM_MS;
}

adopt(css`
  .dp-tooltip:popover-open {
    position: fixed;
    inset: auto;
    margin: 0;
    display: flex;
    align-items: baseline;
    gap: var(--gap);
    max-width: calc(var(--row) * 14);
    padding: calc(var(--pad) / 2) var(--pad);
    border: 0;
    border-radius: var(--radius);
    background: var(--fg);
    color: var(--bg);
    font: var(--fs-small) / var(--lh) var(--font-ui);
    box-shadow: var(--shadow);
  }
  .dp-tooltip .kbd.plain {
    color: inherit;
    opacity: 0.7;
  }
`);
