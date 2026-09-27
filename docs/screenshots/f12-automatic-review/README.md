# A review step and its conversation (F12)

Two scripts render these, each over a throwaway library and throwaway per-user settings:

- `uv run python scripts/render_graph_editor.py --review --out docs/screenshots/f12-automatic-review`
  renders the canvas: a step ready for review, its review with a live agent, and the step
  that follows the review.
- `uv run python scripts/render_step_details.py --review --out docs/screenshots/f12-automatic-review`
  renders Step Details on the review, two rounds into its conversation.

Re-run them after changing the Review tab, the review's card or how a link into a review
is drawn, and commit the result.

| Image | What it shows |
|---|---|
| `pair-*` | S1 is under review and R2 reviews it. The link into R2 is doubled and chevroned like any auto-progress link, though nobody flagged it: a link into a review auto-progresses by rule. R2 wears its key letter and the speech-bubble medallion. S3 follows the review, not S1. |
| `menu-review-arrow-*` | That link right-clicked. *Auto-progress* is ticked and greyed, and its words say why: R2 is a review, and it takes its subject from review on. |
| `review-tab-*` | The Review tab, from the top: the agent (the default profile first, then each agent CLI); the lenses, with room for skills of the person's own; the round cap; and the conversation. The conversation opens with one line saying whose turn it is, then lists every message as heading, opening line and time. |
| `review-templates-*` | The aspect bar's templates, with Review between Agent and Check. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
