---
paths:
  - "src/dplanner/modules/step_{properties,description,milestone,check,status,ticket}/**"
  - "src/dplanner/modules/project_assets/**"
  - "src/dplanner/modules/*/{aspect,section}.py"
  - "src/dplanner/framework/{aspect_bar,aspect_toggle,inspector,module_data_section,prose_edit,prose_section,markdown_toolbar,markdown_highlight,markdown_view,text_binding,text_dialog,asset_gallery,asset_picker,mime_files,image_preview,cards,step_selection}.py"
  - "src/dplanner/domain/{aspects,assets,shelf,migrations}.py"
  - "src/dplanner/core/{module_data,formats}.py"
  - "src/dplanner/cli/{aspects,assets}.py"
  - "tests/framework/test_{aspect_bar,prose_edit,markdown_toolbar,markdown_highlight,text_dialog,asset_gallery,asset_picker,image_preview}.py"
  - "tests/modules/test_{step_properties,step_details,aspect_editors,aspects,asset_sources,project_assets,step_description_section,step_milestone,step_status}.py"
  - "tests/domain/test_{shelf,assets}.py"
  - "tests/cli/test_asset_verbs.py"
  - "scripts/render_step_details.py"
---

# Step panel — aspect toggles, the shelf, Details blocks, prose editors and assets

- **A toggleable aspect's tab follows the aspect.** Milestone, Feature, Agent, Ticket, Test
  and Check are Step ▸ Type toggles (independent, never a radio group), and each registers its
  `InspectorSection` with a `shown_for` predicate so its tab exists only on a step that
  carries the aspect. **The description is an agent step's instructions** — the briefing's
  `## Instructions` block, decided by the composition root's `_briefing_instruction`; a
  *separate* instruction (the checkbox in the Details tab's Description block,
  `dplanner agent set`; dropped atomically with `agent set --clear`) is the opt-out for a
  step whose how-to-execute differs from what-it-is. `ARCHITECTURE.md`'s *The description
  is the instructions* has the reasoning.
- **Every step tab follows a toggle, and absence encodes the default — in both directions.**
  Estimate, Description and GitHub are toggles too now. For most aspects absence
  means *off* and the stored `{"on": true}` marker records the claim; for **Estimate and
  Description absence means *on*** and the marker (`{"off": true}`) records the opt-out,
  because most steps are work and work has a size and a name. That is one `FORMAT.md` rule
  applied honestly, and it is what makes the change cost existing projects nothing. The
  Details tab is its blocks, and always shows: the name leads it, and a step always has one.
  The CLI half of the two opt-outs is `dplanner estimate clear` and `describe clear`, which
  therefore mean **off**, not "empty" — for an aspect whose default is on there is nothing
  else clearing could sensibly mean, and lint skips a step that has opted out.
- **Turning an aspect off shelves it; nothing asks and nothing is lost.** The entry and
  the prose move to `modules/shelf.json` beside the step (`domain/shelf.py`: `turn_off`,
  `turn_on`) and come back on the next toggle-on; with the entry genuinely absent, no
  reader learns a new key. Every Type toggle is one `framework/aspect_toggle.py` call —
  the module hands over `enabled`, a `fresh` entry and (for the two opt-out aspects) what
  to `leave` — and every CLI `clear`/`off` verb applies the same `turn_off`. The migration
  pass reaches into the shelf (`migrate_shelved`) and the asset catalog counts a shelved
  prose's links as uses. `FORMAT.md` has the shape; `ARCHITECTURE.md`'s *Turning an
  aspect off shelves it* has the reasoning.
- **The aspect bar across the panel's top renders the Type submenu, never a copy of it.**
  `framework/aspect_bar.py` puts every Type toggle **on the left, in a `Toolbar`**
  (`framework/toolbar.py`) as a glyph with its words in the tooltip, and runs each through
  `ActionRegistry.run`, so a toggle keeps its own undo command. **What no longer fits folds
  into that strip's `…` menu as glyph *and* words** — never Qt's `»`, which pops the hidden
  buttons up as glyphs again. The strip is **dense**: these glyphs are read as one set
  rather than aimed at one at a time, and at the verb strip's metrics only five of the ten
  toggles fit the width the panel can actually be. **On the right is one dropdown named
  *Template*** — `StepPropertiesDeps.templates`, named by the composition root: a label and
  the *set* of toggles that are on (Step, Milestone, Feature, Agent, Check). The face says
  what it offers and never changes; **which template the step amounts to is the ticked
  entry**, so the bar reads as the toggles plus a way to set them all at once rather than as
  two claims about the step. Picking one runs every toggle that differs inside
  **one `UndoService.gesture`**, and a template reads as selected exactly when the step
  carries its set and nothing else — a combination is a template, both ways, computed on
  every refresh and never stored — and **Step is the catch-all**, worn for any combination
  no other template names. **The face sits outside the `Toolbar`**: a widget on a strip
  hides when there is no room, and the one control saying what the step *is* must survive
  every width — the canvas's layout picker and the *Updating…* indicator sit outside theirs
  for the same reason. **The tone rides on each entry's glyph in the menu, never a fill** —
  a feature's entry and a feature node are one identity, and a face that carried the tone
  would repaint the bar's corner every time the step's kind changed. It takes the
  context as a **function**, so the panel inside the details dialog names its own step, and
  it **announces every refresh** (`refreshed`) for a host that repeats its answer — the
  dialog's lead — because applying a template ends with the bar's own refresh, after the
  last write anybody heard. **A toggle never reports `visible=False`**, and a strip that
  re-shows what fits on every reflow could not honour it: **"this type can never carry that
  aspect" needs no new mechanism** — a toggle returning `ActionState(enabled=False,
  label=…)` is the existing *disabled, never hidden* rule; do not build one until it is
  asked for.
- **The step panel's first tab is Details, composed from blocks.** A module that wants its
  editor there instead of behind a tab of its own registers into `services.step_details` —
  the `InspectorSectionRegistry`'s third instantiation; estimate, description and the spec
  figures are the registrants, and `modules/step_properties/details.py` stacks them
  (`stretch` on the section says who gets the leftover height, `shown_for` hides a block
  with nothing to say). **A block host gives the leftover to a trailing `addStretch(0)`
  and caps every stretch-0 block at `QSizePolicy.Maximum`** — both halves, or the blocks
  scatter when the one that wanted the height is turned off. A `QWidgetItem` reports itself
  expanding when the widget's *own* layout does, so without the cap every block is
  expansive whatever its section declared; the cap is what makes `stretch` authoritative,
  and the stretch is zero or it splits the leftover with the block that asked for it.
  `ARCHITECTURE.md`'s *The Details tab hosts the same contract, as
  blocks* has the reasoning — including why a host is a registry instance, never a flag.
- **A large text field expands into a modal editor** — `framework/text_dialog.py`: a
  second `TextBinding` over the same `TextField`, live-synced through the foreign-change
  path, opened from the corner button `attach_expand` pins onto the editor.
  `ARCHITECTURE.md`'s *Expanding an editor is a second binding, not a copy* has the
  reasoning; never copy text out into a dialog and back.
- **Every prose editor wears the markdown strip, and a verb on it is one splice.**
  `framework/markdown_toolbar.py` over any `ProseEdit`: dense and un-banded, because a
  banded strip's squares put twelve verbs past the 360 px dock every prose editor lives in.
  A verb is a pure `Splice` applied in one `insertText` — Qt reports a `contentsChange` per
  edit *block*, so two operations inside one would make a bound host push the whole
  document — it leaves selected whatever a second press would act on, and it seals the undo
  either side the way `ProseEdit._embed` does. **Its keys are `QShortcut`s on the editor at
  `WidgetShortcut`**, and `Toolbar.add_verb(keys=…)` only prints them: a shortcut on the
  strip's own action would fire wherever the window has focus, which is the canvas-key rule
  from the other side.
- **A file pasted or dropped into a prose editor is attached, then linked.** `ProseEdit`
  (`framework/prose_edit.py`) content-addresses it into the module's file area — the same
  place `describe attach`, `note attach` and `test attach` write — and types
  `![alt](assets/…)` at the caret, or `[name](assets/…)` when it is not an image. A plain-text
  markdown editor cannot embed a picture without breaking `TextBinding`, so it does not
  pretend to; the gallery under it shows the thumbnail. The link is undoable and the blob is
  not (`FORMAT.md`), and the insert **seals the undo step on both sides** or it would merge
  into the sentence being typed. The editor never resolves the area itself: it is handed
  `AssetGallery.attach_bytes`, and `ProseSection.set_area` aims both — called by the host,
  because a test's body is keyed by the test while its images belong to the step. What counts
  as an arriving file is `framework/mime_files.py`, shared with the spec module's rich-text
  editor so the two cannot disagree about a drop. Every prose editor in the application has
  it. `ARCHITECTURE.md`'s *A pasted image is an attachment and a link, not an embed* has the
  reasoning.
- **The asset library is a derived union, and reuse is a copy.** Every file-carrying module
  exports an `asset_source()` from its Qt-free half saying what its areas hold and what
  still uses each file; `domain/assets.catalog()` is one derivation with three readers —
  the Assets tab (`modules/project_assets/`), `dplanner asset list`/`uses` and `asset
  prune` — and the composition root's `_asset_sources()` is the one assembly both surfaces
  read. Picking an existing asset into an editor (`Insert from Assets…`, wired as
  `ProseSection.set_picker` beside `set_area`) copies bytes into the target's *own* area
  through the ordinary attach path, so a link never points into another module's
  directory; identical bytes carry identical content-addressed names, which is what lets
  the browser group them as one asset. Display names are the browser module's project
  metadata (`{"titles": …}`), never part of a link — renaming cannot break a reference.
  Agent-instruction files are used *by existence* (briefings carry the area wholesale)
  and a note's file while a note links it; the pool (`asset attach`) is `prunable=False`; `asset prune` is dry-run by
  default and never enters a directory no source scanned. `ARCHITECTURE.md`'s *An asset
  library is a view, not a store* and *Inserting an existing asset is a paste with a
  different source* have the reasoning.
- **Renaming a module is a `Takeover`, not a migration.** The on-disk id is the contract
  between the old module and the new one, so the successor's package carries the retired
  id and a converter and the data moves at open — see `modules/estimation/aspect.py` and
  `FORMAT.md`'s *Retiring a module*. No project-format change, and no module importing
  another.
- **A module that writes a number owes it a `float`.** An `int` writes as `5` where a
  reloaded float writes as `5.0`, making a file's bytes depend on whether the project had
  been reopened. `module_data` is opaque to the model, so the coercion belongs in the
  aspect's `write()` — see `modules/estimation/aspect.py`.
- **A kind is what a node *is*; a facet is what it carries.** Milestone, Feature, Check and
  Agent Step are kinds — a node exists in order to be one, and wears a body colour for it:
  purple a milestone, **teal a feature**, green a done step (`BODY_TONES` in
  `theme/tones.py`; done outranks milestone outranks feature, and the medallion still says
  what else the node is). An estimate or a description is a facet. The **aspect bar's
  right** is one dropdown naming the *template* the step amounts to — a kind with the
  facets it usually carries — which is why that list is named in the composition root
  (`StepPropertiesDeps.templates`) rather than derived from the Type submenu; the bar's
  left is every toggle, as a glyph. **Step ▸ New is one verb**: a step is born plain, titled "New
  step", and the details dialog opens on it with the name selected, where the bar says
  what it is.
- **A module's project-level editor is a card, registered into `services.detail_cards`.**
  Same `InspectorSection` contract as a step tab, with a project id in `show_target`; the
  project panel renders the stack. Register before `project_editor` in `default_modules()` —
  the panel is built from whatever has registered by then. The agent instruction's card is
  the example; `ARCHITECTURE.md`'s *The project panel hosts the same contract, as cards*
  has the reasoning.
