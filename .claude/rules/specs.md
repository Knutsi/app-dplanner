---
paths:
  - "src/dplanner/modules/{spec,spec_folder,spec_git,spec_confluence}/**"
  - "src/dplanner/domain/document_{folder,source}.py"
  - "src/dplanner/core/secrets.py"
  - "tests/modules/{test_spec,test_confluence,spec_git_helpers}*.py"
  - "tests/cli/{test_spec_,spec_helpers}*.py"
  - "tests/domain/test_document_*.py"
  - "tests/core/test_secrets.py"
  - "scripts/render_spec{_sources,s_tab}.py"
---

# Specs — the spec editor and its document sources

- **Editing a spec in-app is a replace, and a document this project owns has no read
  mode.** Picking its row opens the editor and starts the session; picking another row or
  closing the tab ends it; the idle flush persists in between. The session flushes as one
  `spec import`-style replace: blob written straight to the file area, the index through
  one merged command, `previous` pinned to the session's base so `spec diff` shows the
  session, and only blobs the session itself superseded pruned. **The editor is the prose
  stack's** — a `ProseEdit` with the markdown highlighter, the markdown strip and the
  gallery of what it links to, like every other prose editor here — so **plain text edits
  too**: the old carve-out was the rich-text round-trip handing a `.txt` back as markdown,
  and nothing round-trips now. A PDF is the one document that is not text, and renders.
  Expanding it (⤢) is `ExpandedTextDialog.over_document`: the *same* `QTextDocument`, one
  buffer and two views, because the buffer rather than the model is the authority here —
  never store `editor.document()` in a field. `ARCHITECTURE.md`'s *Editing a spec in-app
  is a replace* has the reasoning.
- **Renaming a spec document moves the name every command addresses it by.** A name is the
  document's identity — `spec show`, `spec diff`, a feature's citation, a page's `parent`,
  an asset row's provenance — so `spec rename` and the tab's *Rename* move all of them in
  one `CompositeCommand`, and the filename's stem follows with its suffix. The citations
  are another module's data, so the composition root composes them
  (`_rename_spec_references`) and both surfaces push the same object. `rename_refusal` is
  the one sentence both use: a name that slugs to nothing, one already taken, and a
  document a source fetched, whose name belongs to the page it came from. **Delete takes
  the index row and never the blob** — undo has to restore a row that still points at
  something, and `previous` is a second pointer at the same file.
- **A source says what it has waiting, and the tab says so before you open it.**
  `updates_words(refresher.stale(project))` is the line over the whole tree with *Refresh
  All* beside it; `UPDATES_MARK` is its short form on the tab title and on the Specs row in
  the index, fanned by `SpecModule.updates_changed` — a **set-diff** signal, never
  `refresher.changed`, which also fires on every busy flip and would redraw the index
  folder on each spinner tick. Checking follows whether a Specs tab is **open**, not
  whether it is the pane in front, so the mark is worth looking at; a project nobody has
  opened is not checked and wears none. A `SourceStatus` must claim `connectable` for
  Connect to be offered — a malformed locator is a refusal no dialog lifts, and the strip
  gives it the error tone instead.
- **A spec source is a kind the spec module runs, and there are four.** A document may
  come from outside — a **folder** on this computer, a **git repository**, a **Confluence
  page**, a **Confluence folder** — and *where it came from* is a source record in the
  spec index (format 5: `sources` with the kind's own id and locator, and
  `source`/`key`/`version`/`parent`/`title` on a document; absence still means
  project-owned and editable). A **document source kind** is the Protocol in
  `modules/spec/source_kind.py`: it locates, says whether it is connected, connects,
  fetches and checks; the spec module owns the records, the nested tree, the write
  (`sourced.apply_snapshot`, through `import_document`, so a refreshed document keeps
  `previous` and `spec diff` answers per document), the task (`spec/refresh.py`), the
  undo entry and the freshness note. A fetched document is **bytes and a filename** —
  markdown, text or a PDF — and the spec module keeps its own minted name as the stem and
  takes only the suffix, so no kind can rename every row of an existing plan. The + button's
  arrow renders the Project ▸ *Add Spec* child menu, so a kind contributes one `ActionSpec`
  and nothing else; the root names the kinds in `_source_kinds`, which is also the test
  seam and where the menu's order is decided. **Two kinds may be one module**:
  `spec_confluence` is one client, one credential and one Connect dialog under a
  `ContentType` record constructed twice — the walk stays one function, and `expected` on
  `parse_url`/`valid_locator` is what refuses a folder address pasted into the page kind.
  **Refresh is a person's gesture and lands on the undo stack** — one gesture is **one
  undo entry**, so `refresh` is `refresh_all` over a list of one (`break_coalescing`
  first, so two refreshes are two entries); **a check writes nothing** — `check_all`
  compares versions on the interval and the strip says "N documents changed — Refresh".
  **`locate` may reach the network, off the GUI thread**: the rule is never block it, and
  the git kind's *which folder?* cannot be answered without asking. A sourced document is
  shown read-only, `spec import`/`spec remove` refuse it, and fetching is **window-only**
  — a fetch pulls bytes from outside the plan into it, and that is a person's act.
  `ARCHITECTURE.md`'s *A spec source is a kind the spec module runs* has the reasoning.
- **A folder of documents is one walk, in `domain/document_folder.py`.** The folder kind
  and the git kind both read it and may not import each other. A **key is the path**
  relative to what was scanned; documents **nest under their directory's index document**
  (`README.md`/`index.md`), and a directory with none is transparent — so a tree with no
  index documents lands exactly flat; a **version is a digest over the body *and* the
  pictures it links**, because a diagram redrawn beside untouched text would otherwise
  leave the row kept and the page showing a blob that is gone. `is_document` is exported
  because the git kind's `check` derives the same key set from a git tree: two rules for
  what a document is would make a check lie about every file in the gap.
- **A git spec source is a cache, never the plan — and the clone door is
  `core/storage/sparse.py`'s.** `SparseClone(cache_root, url, ref, path)` is the blobless,
  shallow, sparse clone under `config_dir()/spec-git/<digest of url + ref + path>` — one
  directory per position, so two sources can never cross sparse patterns — and the module
  only reads it: `source.py` builds the locator's clone, hands the walk's `is_document` to
  the listing, and turns a `GitError` into the `SourceUnavailableError` a person reads.
  The **size guard runs before one blob exists**: `--filter=blob:none` brings the trees,
  `tree()` counts what `materialise()` would take in, and an oversized folder is refused
  *while it is being chosen*, naming the folder (`Folder.refusal`). A **version is the
  file's blob oid**, which is what lets `check` name changed, added and gone documents from
  the trees alone — a commit id moves for every file in the repository and would report the
  whole source changed. **Nothing can hang a worker thread**: prompts are off four ways, one
  transport is allowed and it is the validated address's, every call has a timeout, and a
  kill reaches the process group. The person's own git credentials do the auth and **an
  address carrying one is refused at the door** — `parse_url`, and a `SparseClone` refuses
  to be built over anything it did not accept.
- **An external source's credential is the person's, never the plan's.** A kind may have
  none at all — a folder has nothing to connect to, and a git repository uses the git
  credentials already on the machine, which is why an address carrying a user name and
  password is refused rather than stored. The Confluence
  token lives only in the OS keychain (`secrets_store`, keyed by site — macOS Keychain,
  Linux Secret Service, Windows Credential Manager; `backend_problem()` refuses with the
  remedy when none can keep it, never a plaintext fallback); the site → email row in
  `user_config` is *the fact that a site is connected* and the only thing `status()`
  reads — a state callback runs on every context change and must never make a keychain
  round trip. The token is read inside `fetch`, `check` and the Connect dialog's probe,
  handed to `client.py` as a value; the client has one request method and it is GET,
  talks only to the source's `*.atlassian.net` origin, follows one redirect to an
  Atlassian host without the credential, caps every body, count and wait, and composes
  every error from the status code — never from a library's own message. Content is
  data: `html.parser`, no raw HTML in the markdown, only http(s)/mailto links, images
  only from bytes sniffed as raster and named by their content.
