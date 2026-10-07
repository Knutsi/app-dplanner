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
| `pair-*` | S1 is under review and R2 reviews it. R2 wears its key letter and the speech-bubble medallion. S3 follows the review, not S1. |
| `menu-review-arrow-*` | That link right-clicked: an arrow's own verbs. |
| `review-tab-*` | The Review tab, from the top: the agent (the default profile first, then each agent CLI); the lenses, with room for skills of the person's own; the round cap; and the conversation. The conversation opens with one line saying whose turn it is and *Open Conversation…* beside it, then lists every message as heading, opening line and time, with the glyph of whoever said it (S35). |
| `review-templates-*` | The aspect bar's templates, with Review between Agent and Check. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
