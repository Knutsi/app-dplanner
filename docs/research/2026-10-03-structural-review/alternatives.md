# What could replace or narrow the composition root

**Summary.** The composition root is the right pattern. It has two jobs, and only one of them
belongs to it: it *wires* the modules, and it is also the *only place allowed to know two
modules at once*. A callback hides a dependency without removing it, since `_step_key`
depends on five aspects however it is reached. Seven approaches are compared below on one
running example. The recommendation is the **hybrid (3)**:

- a module may import another module's **headless files**, along an import graph a test keeps
  acyclic
- questions many modules answer become **extension points** on `AspectSpec`, as `phrase`
  already is
- **services** stay on `Deps`

## The running example

Each approach is shown on the same two questions:

1. **Many modules answer: the step's key letter.** `_step_key` (`modules/__init__.py:2837`)
   asks five aspects in a fixed order: milestone `M`, feature `F`, check `C`, wait `W`,
   cut `B`, review `R`, otherwise `S`. It is handed to about 11 modules' `Deps` as
   `key_of=` / `step_key=`.
2. **One pair of modules: the briefing reads a step's PR.** `_briefing_sections`
   (`__init__.py:2197`) and `_source_line` (2308) import `github.aspect.read` to tell an
   agent which branch and PR its source work sits on.

## The approaches

| # | Approach | One line |
|---|---|---|
| 0 | Today | Everything that touches two modules lives in the root and reaches modules as a callback. |
| 1 | Split the root | The same rule; the root becomes a `composition/` package of wiring files per cluster. |
| 2 | Extension points only | Every cross-module question is a contribution; modules still never import each other. |
| 3 | **Hybrid** | Headless imports along an acyclic graph + extension points + `Deps` for services. |
| 4 | Event bus / mediator | Modules ask and answer by topic string. |
| 5 | Service locator | Modules fetch what they need from a global registry by type. |
| 6 | Bounded contexts / hexagonal | Group modules into contexts with ports and adapters between them. |

## Verdict per approach

- **0 Today.** It kept the dependencies visible and the modules independently testable. It
  now costs a 36%-of-commits hotspot, logic with no owner, the same ranking written six
  times, and 480 `Deps` fields.
- **1 Split the root.** It spreads the churn over several files and costs little. But the
  logic still has no owner, the `Deps` stay the same, and the daemon still has to import
  the GUI's wiring to get due steps. Recommended as a mechanical first step whatever else
  is chosen.
- **2 Extension points only.** Ideal for the key letter, where the precedence becomes data
  on each `SPEC`. It is ceremony for a pairwise read: a registry with one consumer and one
  contributor is a callback with extra steps. Branch planning needs github's `pr_base`
  specifically, not "whatever contributes".
- **3 Hybrid.** This is the recommendation:
  - Pairwise reads become plain imports, so mypy checks them and "find usages" finds them.
  - Many-answer questions become `SPEC` fields.
  - The import graph is checked acyclic, and the check is what tells you where code
    belongs. Simulating the move of today's clusters to their owners gives two cycles,
    and both name a real misplacement:
    - `branches → step_agent_instruction → step_status → branches`: the briefing belongs in
      its own `agent_briefing` package.
    - `step_milestone ↔ time_estimates`: milestone colours are the schedule's.

    With both fixed, the graph of 31 edges has no cycles.
- **4 Event bus / mediator.** It hides the dependencies further than callbacks do: a topic
  string cannot be type-checked or found by "find usages". It also adds ordering and
  re-entrancy questions on top of a synchronous signal system that already swallows
  exceptions. Rejected.
- **5 Service locator.** It is the same problem made global, and it breaks the
  several-libraries assumption a daemon needs. Rejected.
- **6 Bounded contexts / hexagonal.** Too much ceremony for one process today. But the
  hybrid's acyclic graph is where contexts would show up later: *Planning* (graph, order,
  schedule), *Execution* (briefing, launch, runs, claims, the daemon) and *Knowledge*
  (spec, docs, topology, the v2 system level). Revisit when the multiplayer server
  exists.

## The enforcing test (sketch)

```python
def test_cross_module_imports_are_headless_and_acyclic() -> None:
    graph: dict[str, set[str]] = {package: set() for package in module_packages()}
    for path in module_files():
        for package, filename in imports_of_other_modules(path):
            assert is_headless(package, filename), (
                f"{path} imports {package}/{filename}, which is not headless"
            )
            graph[package_of(path)].add(package)
    cycle = find_cycle(graph)
    assert cycle is None, "module import cycle: " + " → ".join(cycle)
```

The graph this test would see after the moves:

| Package | Imports headless files of |
|---|---|
| `agent_briefing` | auto_progress, feature, github, notes, spec, step_agent_instruction, step_description, step_review, step_status, step_ticket |
| `branches` | estimation, github, project_editor (stacks), step_agent_instruction (launcher), step_description |
| `coverage` | docs, feature, spec, step_milestone, testing |
| `time_estimates` | estimation, step_agent_instruction, step_milestone, step_status, step_wait |
| `step_status` | step_wait, branches (only for "works nobody"; this edge goes once kinds are an extension point) |
| `step_agent_instruction` | step_review |
| `auto_progress` | step_review |
