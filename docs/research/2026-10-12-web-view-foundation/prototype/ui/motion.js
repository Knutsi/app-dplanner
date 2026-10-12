// Motion, as rules a component cannot forget:
//
//   1. Motion carries information — where something went (flip), what changed under you
//      (flash), where a surface came from (enter), that a state changed. Never ornament.
//   2. State commits first. An animation runs on what is already true, so input is never held
//      for one, and a new change cancels the old motion rather than queueing behind it.
//   3. What is done hundreds of times a day does not animate: keyboard-opened menus, the
//      palette, selection, focus moves. via === "key" means instant.
//   4. Durations are tokens (--dur-*); reduced motion zeroes them, and these helpers check too.

export const still = () =>
  matchMedia("(prefers-reduced-motion: reduce)").matches || document.documentElement.dataset.motion === "reduced";

const ms = (token) => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(token)) || 0;
const ease = (token) => getComputedStyle(document.documentElement).getPropertyValue(token).trim() || "ease";

// A surface appears out of the thing that opened it: a short scale and fade from `origin`
// ("top left", "50% 0"). From the keyboard, it simply appears.
export function enter(el, { origin = "top left", via = "pointer" } = {}) {
  if (via === "key" || still()) return;
  el.animate(
    [
      { opacity: 0, transform: "scale(0.97)", transformOrigin: origin },
      { opacity: 1, transform: "none", transformOrigin: origin },
    ],
    { duration: ms("--dur-small"), easing: ease("--ease-enter") },
  );
}

// Where things went: measure, change, then play each element from its old place to its new.
// Interruptible — a flip started while another runs starts from wherever the element is now.
export function flip(elements, change, { duration = "--dur-layout" } = {}) {
  if (still()) return change();
  const before = new Map(elements().map((el) => [el, el.getBoundingClientRect()]));
  const result = change();
  const time = ms(duration);
  for (const el of elements()) {
    const old = before.get(el);
    if (!old) continue;
    const now = el.getBoundingClientRect();
    const dy = old.top - now.top;
    const dx = old.left - now.left;
    if (!dx && !dy) continue;
    el.getAnimations().forEach((a) => a.id === "flip" && a.cancel());
    el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], {
      duration: time,
      easing: ease("--ease-move"),
      id: "flip",
    });
  }
  return result;
}

// What changed: a one-shot wash, restarted if it changes again mid-fade.
export function flash(el) {
  el.classList.remove("changed");
  void el.offsetWidth; // restart the animation
  el.classList.add("changed");
  el.addEventListener("animationend", () => el.classList.remove("changed"), { once: true });
}

// A crossfade between two states of one slot (the toolbar ↔ the selection bar): the content
// swaps at once, the old picture fades over it. Instant from the keyboard.
export function swap(el, { via = "pointer" } = {}) {
  if (via === "key" || still()) return;
  el.animate([{ opacity: 0.35 }, { opacity: 1 }], { duration: ms("--dur-micro"), easing: "linear" });
}
