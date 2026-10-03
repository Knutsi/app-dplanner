# Questions for you

*2026-10-03. Each question carries a recommendation, so a one-word answer is enough.*

| # | Question | Recommendation | Why |
|---|---|---|---|
| 1 | **A list of gates (a star around the work), or a free stage graph?** | **The list**, with `on_changes` as the one escape hatch | Every case we could name fits it. A graph editor is the "squeezed from both directions" builder. Add a graph only when a real playbook needs one. |
| 2 | **The file format for a playbook definition?** | **TOML** in `<plan repo>/playbooks/`, edited through a form | A person authors it and wants comments in it; the standard library reads it. It is the first hand-authored config in a JSON codebase, so FORMAT.md needs a line on why. The alternative is JSON written only by the form. |
| 3 | **Where do playbooks live?** | Built-in presets, shadowed by the plan repo's `playbooks/`, and later the **system** level (v2 idea 1) | Versioned with the plan, shared by everyone who opens it. Project wins over personal, as Factory droids and Claude workflows do. |
| 4 | **Does an agent's pass stand after another gate's fix?** | **Yes**, unless the fix touches a file the earlier gate flagged | Re-reviewing after every fix doubles the cost. The exception catches the case that matters. |
| 5 | **Build the lead-agent driver?** | **Engine first; the lead later, as an experiment on the same ledger** | The evidence favours the engine. The lead is cheap to add once the engine enforces criteria, fencing and budget, and only running both measures the claim. |
| 6 | **Must a careful playbook have acceptance criteria before it starts?** | **Yes for *Careful change*; offered for the others** | Without criteria every gate is opinion, and opinion over-flags. A drafted validation contract a person accepts in one click is the Factory pattern. |
| 7 | **The default playbook for a new project?** | ***Solo* per step, *Careful change* on branch landings** | The person gate goes where it is paid for once ([floor.md](floor.md)). |
| 8 | **Who answers a person gate?** | **A role, defaulting to the step's owner** | Named people for small teams, roles for the floor, with the same field. |
| 9 | **When only one vendor's CLI is installed, should *Review loop* fall back to a same-vendor fresh review, or refuse?** | **Fall back, and say so on the ring** | It is still the "fresh context + tests" control. Refusing teaches nothing. |
| 10 | **Run the live experiment** (`claude -p` implements, `codex exec --sandbox read-only` reviews, one fix round, on a toy repo in the scratchpad)? | **Yes, once.** It costs roughly $1–3 of subscription usage. | It turns the simulation's assumed tokens and minutes into measured ones, and records a real stream for the transcript viewer. It was not run tonight, because it spends quota and needed your go-ahead. |
| 11 | **Add a harness `classify()` and stall threshold to `AgentHarness`?** | **Yes, with the probe fixtures as its tests** | The probes showed each CLI fails differently (Claude's 3-minute 401 retries, opencode's endless loop). A shared classifier would need to know every CLI's quirks; one per harness keeps each quirk with its CLI. |
| 12 | **Keep the probe runner as a maintained script** (`scripts/probe_harnesses.py`) to re-run when a CLI updates? | **Yes** | CLI error behaviour changes monthly, and a classifier built on last month's shapes fails silently. |
