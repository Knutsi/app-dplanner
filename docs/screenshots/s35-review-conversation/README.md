# A review's conversation, read in full (S35)

One script renders these, over a throwaway library and throwaway per-user settings:

- `uv run python scripts/render_step_details.py --conversation --out docs/screenshots/s35-review-conversation`
  opens the dialog through *Step ▸ Review Conversation…* on a review two rounds into its
  conversation.

Re-run it after changing the dialog, the rows it shares with the Review tab, or how a
message's text is rendered, and commit the result. The Review tab's own images, with the
*Open Conversation…* button that is the dialog's second way in, are in
`../f12-automatic-review/review-tab-*`.

| Image | What it shows |
|---|---|
| `conversation-*` | R2 reviews S1. Every message is listed on the left in the order it was said: the review's findings wear its speech bubble, and S1's reply wears the agent's sparkles. The dialog opens on the newest message, which is rendered in full on the right under its heading and the time it was said. The footer's status slot says whose turn it is and how many of the rounds are spent. |

Each is rendered in the dark and the light theme (`-dark`, `-light`).
