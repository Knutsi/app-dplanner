# S16 — the dialogs and Settings on the frame

Rendered by `uv run python scripts/render_dialogs.py --out docs/screenshots/s16-dialogs`.
Every row is invented rather than probed, and `HOME` and `QSettings` point into a
temporary directory, so no path or preference of the rendering machine reaches an image.

| Image | What it shows |
|---|---|
| `settings-agent-profiles-*` | Settings on the frame: the tree beside the page across a seam, Close alone. Agent profiles is a strip of verbs over a two-line table — the default the bold row, *Remove* greyed with its reason — beside the editor, every field under its caption and the standing explanations behind the caption's glyph. |
| `settings-appearance-*` | Appearance: one caption over the providers, each a switch over what it can do here. |
| `settings-openai-*` | A page that was a `QFormLayout`: captions over the fields, and *Refresh* a quiet button whose glyph the arc turns in while a status line under the row says where the fetch stands. |
| `settings-confluence-*` | Connected sites as a table with *Reconnect…* and *Forget* on a strip above it, greyed until a site is picked. |
| `project-settings-*` | The Project dialog with Close alone, every edit live; both repositories apart, their logs side by side. |
| `project-colocated-*` | A plan still inside its code: the warning, and the plan column's empty state carrying *Set up a plan repository…* as its verb. |
| `project-create-*` | New Project: the plan repository, the folder, and the Locations table over a draft — empty, saying what to add first — with *Create* refused in words: a project already exists at that folder. |
| `location-add-*` | Add Location: the repository as a combo of what the library names and what gh knows, its refresh glyph and ⋯ (*From a folder on this computer…*); the position with *Browse…* over the checkout or the remote's tree; the role's summary as the hint. |
| `open-project-ways-*` | Open Project, page one: the two ways in as a captioned list of two rows, in the room the later pages need — the wizard never resizes on screen; *Continue* the primary. |
| `open-project-link-*` | The link page: what the link names, where the plan will be cloned, and where the code should go — each under its caption, *Back* beside Cancel. |
| `open-project-browse-*` | The browse page: the plan repository under its caption, the projects it holds with who worked on each, and the primary worded with the count. |
| `share-project-*` | Share Project: what the link sets up and what it does not grant, the link itself, and the same link as a QR code — dark on light whatever the theme, because a camera reads it. *Copy Link* the primary, *Save File…* quiet beside Close. |
| `move-plan-*` | Move Plan: the repository picker — its other ways in one ⋯ menu — and the folder under their captions, the path they make under the folder. |
| `repositories-folder-*` | The first clone's question: *Browse…* a quiet secondary beside Cancel, out of the far-left slot a destructive verb owns. |
| `gh-repo-list-*` | Clone from GitHub: the filter under its caption, and the listing's count in the footer's status slot. |
| `install-*` | Install DPlanner: the rows read as the Setup Checklist's, ☐ in the error tone for what an agent needs and the information tone for the launcher; *Remove* at the far left, *Update* the primary. |
| `install-done-*` | The same after the install: ☑ on every row and *Done* in the status slot. |
| `prompt-fallback-*`, `prompt-copied-*` | No terminal opened: the prompt in a text well, and *Copy Prompt* saying what it did. |
| `run-anyway-*`, `run-anyway-many-*` | The graph's question before a launch, on the frame: the launch count in the title, what each step waits on under it, *Run Anyway* the primary. |
| `asset-picker-*`, `asset-picker-empty-*` | Insert from Assets: *Insert* the primary with two picked; with nothing to pick, the empty state stands in for the grid and *Insert* is refused. |
| `image-preview-*`, `image-preview-missing-*` | The lightbox with its two verbs as quiet secondaries; a file gone from disk is said in the status slot rather than a box over the picture. |
| `diff-*` | Changes Since Last Save: the repository picker under its caption, a monospaced text well, *Save Now* the primary. |
| `connect-*`, `connect-refused-*` | Connect to Confluence, opening on the email; refused with its reason when this machine cannot keep a token. |
| `conflict-*`, `conflict-refused-*` | Changed here and outside: the agent the primary, and refused with its reason in the status slot, its name kept. |
| `chart-*` | Every progress plot in a window of its own: an editor dialog, Close alone. |
| `expanded-text-*` | An editor in a window of its own: the markdown strip over the text, Close alone. |

Dark and light (`-dark`, `-light`).
