// The modeline: the window's foot, and the place the keyboard explains itself. At the left,
// the mode — always named, always with its way out. Beside it, the echo of the last command
// and its key, however it was run: a keyboard user gets confirmation, a mouse user learns the
// key without a lecture. In the middle, the context as a breadcrumb of URIs; at the right,
// whatever the shell puts there (activity, theme, counts).

import { DpElement } from "../engine/element.js";
import { html, nothing, repeat } from "../engine/template.js";
import { glyph } from "./glyph.js";
import { kbd } from "./keys.js";
import { adopt, css } from "./style.js";

const isItem = (x) => x && typeof x === "object" && "label" in x && !("strings" in x);

export class StatusBar extends DpElement {
  static shadow = false;
  static props = {
    mode: { type: Object, value: { name: "—", exits: null, tone: "none" } },
    echo: { type: Object, value: null },
    crumbs: { type: Object, value: [] },
    right: { type: Object, value: [] },
    verbs: { type: Object, value: [] },
    showVerbs: { type: Boolean, value: false, attribute: "verbs" },
  };

  connected() {
    this.setAttribute("role", "status");
  }

  #echo(echo) {
    if (echo.refused) {
      return html`<span class="echo refused">${kbd(echo.keys)}<span>${echo.refused}</span></span>`;
    }
    if (echo.source === "pointer") {
      // Ran with the mouse: name it, then the key that would have done it.
      return html`<span class="echo">${echo.label}${echo.keys ? html`<span class="learn">·</span>${kbd(echo.keys)}` : nothing}</span>`;
    }
    return html`<span class="echo">${kbd(echo.keys)}<span>${echo.label ?? ""}</span></span>`;
  }

  render() {
    const { name, exits, tone } = this.mode ?? {};
    const echoes = this.echo ? [this.echo] : [];
    return html`
      <span class="mode" data-tone=${tone ?? "none"}>${name}</span>
      ${exits ? html`<span class="exits">${exits}</span>` : nothing}
      <span class="echo-slot" aria-live="polite">${repeat(echoes, (e) => e, (e) => this.#echo(e))}</span>
      <nav class="crumbs" aria-label="Context">
        ${this.crumbs.map(
          (c, i) => html`${i ? html`<span class="sep" aria-hidden="true">›</span>` : nothing}<span class="crumb" title=${c.uri ?? nothing}>${c.label}</span>`,
        )}
      </nav>
      ${this.showVerbs && this.verbs.length
        ? html`<span class="verbs">${this.verbs.map(
            (v) => html`<span class="verb" aria-disabled=${v.disabled ? "true" : nothing} title=${v.reason ?? nothing}>${kbd(v.keys)}<span>${v.label}</span></span>`,
          )}</span>`
        : nothing}
      <span class="right">${this.right.map((r) =>
        isItem(r)
          ? html`<button class="item" type="button" title=${r.tip ?? nothing} @click=${() => r.run?.()}>${r.icon ? glyph(r.icon) : nothing}<span>${r.label}</span></button>`
          : r,
      )}</span>`;
  }
}
StatusBar.define("dp-statusbar");

adopt(css`
  dp-statusbar {
    display: flex;
    align-items: center;
    gap: var(--gap);
    height: var(--menubar);
    padding: 0 var(--pad) 0 0;
    background: var(--bg-sunken);
    border-top: var(--rule);
    color: var(--fg-2);
    font-size: var(--fs-small);
    white-space: nowrap;
    overflow: hidden;
    --icon: 14px;
  }
  dp-statusbar .mode {
    flex: none;
    align-self: stretch;
    display: flex;
    align-items: center;
    min-width: 4.5em;
    justify-content: center;
    padding: 0 10px;
    font: 700 var(--fs-small) / 1 var(--font-mono);
    letter-spacing: 0.06em;
    color: var(--fg-3);
    border-right: var(--rule);
    transition: background-color var(--dur-micro) linear, color var(--dur-micro) linear, box-shadow var(--dur-micro) linear;
  }
  dp-statusbar .mode[data-tone="nav"] { color: var(--accent); box-shadow: inset 0 -2px 0 var(--accent); }
  dp-statusbar .mode[data-tone="edit"] { background: var(--tone-busy); color: var(--bg); }
  dp-statusbar .mode[data-tone="pending"] { background: var(--tone-warn); color: var(--bg); }
  dp-statusbar .mode[data-tone="transient"] { background: var(--accent); color: var(--on-accent); }
  dp-statusbar .exits { color: var(--fg-3); }
  dp-statusbar .echo-slot { display: flex; min-width: 0; }
  dp-statusbar .echo {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--fg);
    animation: dp-echo-in var(--dur-micro) linear;
  }
  dp-statusbar .echo .kbd kbd { padding: 1px 4px; border-bottom-width: 1px; }
  dp-statusbar .echo .learn { color: var(--fg-3); }
  dp-statusbar .echo.refused { color: var(--tone-error); }
  @keyframes dp-echo-in { from { opacity: 0; } }
  dp-statusbar .crumbs { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: safe center; gap: 6px; overflow: hidden; }
  dp-statusbar .crumb { min-width: 2em; overflow: hidden; text-overflow: ellipsis; }
  dp-statusbar .crumb:last-child { color: var(--fg); }
  dp-statusbar .sep { color: var(--fg-3); }
  dp-statusbar .verbs { display: flex; gap: 12px; }
  dp-statusbar .verb { display: inline-flex; align-items: center; gap: 4px; }
  dp-statusbar .verb[aria-disabled="true"] { color: var(--fg-3); }
  dp-statusbar .verb .kbd kbd { padding: 0 3px; border-bottom-width: 1px; color: var(--accent); }
  dp-statusbar .right { display: flex; align-items: center; gap: 4px; }
  dp-statusbar .item {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: calc(var(--menubar) - 6px);
    padding: 0 6px;
    border: none;
    border-radius: var(--radius);
    background: transparent;
    color: inherit;
    font: inherit;
  }
  dp-statusbar .item:hover { background: var(--bg-hover); color: var(--fg); }
`);
