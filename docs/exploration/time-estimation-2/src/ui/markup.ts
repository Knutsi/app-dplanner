/** Small helpers for building SVG and HTML as strings, and elements by hand. */

export const INK = "var(--ink)";
export const SECONDARY = "var(--secondary)";
export const SURFACE = "var(--surface)";
export const PLAN = "#5f87d7";
export const GOOD = "#78c88c";
export const BAD = "#dc6e6e";
export const ATTENTION = "#dcaa5a";

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };

export function esc(text: string): string {
  return text.replace(/[&<>"]/g, (char) => ESCAPES[char]);
}

/** A coordinate, short: SVG does not need sixteen digits. */
export function n(value: number): string {
  return String(Math.round(value * 10) / 10);
}

export function clip(text: string, room: number): string {
  return text.length <= room ? text : text.slice(0, room - 1).trimEnd() + "…";
}

/** An average glyph's width as a share of the font size — the report's estimate. */
export function textWidth(text: string, font = 11): number {
  return text.length * font * 0.56;
}

type Child = Node | string | null | undefined | false;

/** An element with attributes, listeners (`on…`) and children. */
export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Record<string, unknown> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      element.addEventListener(key.slice(2), value as EventListener);
    } else if (key === "html") {
      element.innerHTML = String(value);
    } else if (key in element && key !== "list" && typeof value !== "string") {
      (element as unknown as Record<string, unknown>)[key] = value;
    } else {
      element.setAttribute(key, value === true ? "" : String(value));
    }
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child);
  }
  return element;
}
