# Spec sources: pluggable importers, Confluence first

*Proposal, 2026-09-07. Status: **implemented** on this branch the same day, in the §6
order; `ARCHITECTURE.md`'s *A spec source is a kind the spec module runs* is now the rule's
home and `FORMAT.md` the shapes'. Two things moved during the build: `SourceStatus` lives
in `domain/document_source.py` beside the other shapes (a Protocol method must return a
type both modules can name), and the kind's `icon` is a method. Originally: Written from a full read of the code at `main` (0fbfa01) and a review pass against it; every file and line named below is on that commit. Decisions taken with the author: fetching is window-only, the tab checks and asks, Cloud only, one document per page nested; macOS and Linux are first-class and Windows if viable, so §4.1 covers key storage on all three.*


## Context

Specs today are files a person puts beside the project: a PDF, a markdown or text file
imported by `spec import` / *Import Spec Document…*, or a markdown document written in the
Specs tab. The index (`modules/spec.json`, format 3) knows a document's name, kind and
content-addressed blob; `previous` keeps the superseded blob so `spec diff` works; features
cite passages by quote and digest.

The spec increasingly lives elsewhere and changes there — Confluence first, other systems
later. The revision makes **where a document comes from** a first-class, pluggable fact:

- The Specs tab's **+** becomes a dropdown of *ways to add a spec*: the two built-ins (new
  markdown, import a file) and one entry per **source kind** a module contributes.
- A **Confluence** kind: paste a page or folder URL; the tree under it is downloaded as one
  markdown document per page (images included), nested in the list, read-only, refreshable,
  diffable, and citable exactly like any other spec document. Read-only against Confluence
  by construction; the API token lives in the OS keychain and never reaches the plan.
- Decisions taken with the user: fetching is **window-only** (an agent's shell can never
  exercise the token); the tab **checks** for changes and asks, never auto-downloads;
  **Cloud only** in this revision (Data Center designed for as a later client row); **one
  document per page, nested**. Platforms: **macOS and Linux first-class, Windows if viable**
  — safe key storage on all three (§4.1).

Sections: (1) research and gotchas, (2) design, (3) file-by-file work, (4) security,
(5) verification. A Plan-agent review of the first draft was folded in; the items it changed
are marked *(review)* where the reasoning is not obvious.

---

## 1. Confluence Cloud: what the research settled

Sources: Atlassian's docs via search summaries (developer.atlassian.com is blocked from this
sandbox), community threads, and three mature open-source readers (`sooperset/mcp-atlassian`,
`Spenhouet/confluence-markdown-exporter`, `atlassian-api/atlassian-python-api`).

**Auth and base URL.**
- Classic (unscoped) API token: HTTP Basic `email:token` against
  `https://<site>.atlassian.net/wiki/api/v2/…`. This is what we support first.
- Scoped tokens must go through `https://api.atlassian.com/ex/confluence/{cloudId}/wiki/api/v2/…`
  (cloud id from `https://<site>.atlassian.net/_edge/tenant_info`, unofficial but universal),
  need granular scopes (`read:page:confluence`, `read:attachment:confluence`,
  `read:space:confluence`, `read:content-details:confluence`; the hierarchy scope
  `read:hierarchical-content:confluence` is *missing from the token UI*, CONFCLOUD-82041),
  and **attachment downloads 401 with scoped tokens** on `/download/attachments/` (several
  2025 threads; the v1 `…/child/attachment/{id}/download` path is the workaround). Classic
  tokens now; the client keeps a `gateway` seam so scoped tokens are a later row.
- **Tokens expire**: hard 1-year maximum since Jan 2025; older tokens expired Mar–May 2026.
  Reconnecting is a normal event — the UI must make it one click.
- Unscoped tokens are "deprecated, no date"; API-token rate limiting since 22 Nov 2025.

**Endpoints (v2; v1 is being removed endpoint by endpoint and we do not use it).**
- `GET /pages/{id}?body-format=storage` → `id, title, status, version.number, parentId,
  parentType, spaceId, body.storage.value, _links.webui`; `subtype: "live"` for live docs.
- `GET /pages/{id}/direct-children?limit=250` and `GET /folders/{id}/direct-children` →
  `results[{id, type, title, status, childPosition}]`, types `page|folder|whiteboard|
  database|embed`; descend into `page` and `folder`, note the rest. `GET /folders/{id}`
  gives a folder's title.
- `GET /pages/{id}/attachments?limit=250` → `results[{id, title, mediaType, fileSize,
  fileId, version.number, downloadLink}]`; `downloadLink` is site-relative
  (`/download/attachments/{pageId}/{name}?version=N&…`), fetched as
  `https://<site>.atlassian.net/wiki` + link with the same Basic auth; it may 302 to a
  signed media URL.
- Freshness: `GET /pages/{id}/descendants?limit=250` (minimal rows, no versions) then
  `GET /pages?id=<csv>&limit=250` (bulk get, carries `version.number`). Two or three
  requests for a tree of ≤250 pages, no bodies. Fall back to the children walk if
  descendants 4xx's.
- Pagination is **cursor-based**: follow `Link: <…>; rel="next"` or `_links.next`, a
  *relative* URL that already starts with `/wiki/…`. Never mix v1 offset params in.

**Errors.** 401 = token invalid/expired/revoked (Atlassian's body says the misleading
"Basic authentication with passwords is deprecated"). 403 = no product access or an
anonymous fall-through ("Current user not permitted to use Confluence"). 404 = page gone
*or* not permitted (Confluence hides). 429 = `Retry-After` seconds — values up to ~1800 seen,
and one library crashed on it. 5xx = retry.

**Storage format (XHTML with `ac:` / `ri:` namespaces) — what a converter must know.**
- Images: `<ac:image ac:alt="…" ac:width="…"><ri:attachment ri:filename="x.png"
  ri:version-at-save="3"/></ac:image>` (match by attachment `title`), or `<ri:url
  ri:value="https://…"/>` (external — never fetched by us).
- Links: `<ac:link><ri:page ri:content-title="…" ri:space-key="…"/><ac:plain-text-link-body>
  <![CDATA[text]]></ac:plain-text-link-body></ac:link>`, `ri:attachment`, `ri:user
  ri:account-id="…"` (mention; display name needs another call — render `@user`), plain
  `<a href>`, and `<a data-card-appearance>` smart links.
- Macros: `<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">…
  </ac:parameter><ac:plain-text-body><![CDATA[…]]></ac:plain-text-body>`; panels
  `info|note|warning|tip|panel|expand` carry `<ac:rich-text-body>`; `status`, `toc`, `jira`,
  `include`, `excerpt-include`, `children`, `drawio`, `gliffy`, `plantuml` are **dynamic —
  their content is not in storage**; render a labelled placeholder (drawio/gliffy usually
  leave a `<name>.png` preview attachment worth embedding when present).
- Also: `ac:layout*` (transparent), `ac:task-list`/`ac:task`/`ac:task-status` (`- [ ]`),
  `ac:emoticon ac:name`, `<time datetime>`, `ac:placeholder` (editor-only, drop),
  `ac:inline-comment-marker` (unwrap), `ac:adf-extension` (placeholder), tables with
  `data-layout` and `<colgroup>`. CDATA end tags may be spaced (`]] >`). Generic HTML parsers
  choke on the namespaced tags — every serious reader hand-handles `ac:*`.

**Gotchas from the field, folded into the design.** Cursor-vs-offset mixups; `_links.next`
as string vs dict and relative to `/wiki`; Retry-After overflow; Basic auth dropped on a
cross-host redirect and, conversely, an Authorization header *forwarded* to a foreign host;
title-based filenames colliding and containing path characters; unbounded attachment /
plantuml decompression (the exporter caps at 4 MiB); `body.storage` empty for some live
docs; `status != current` rows in children lists.

---

## 2. Design

### 2.1 One new contract: a *document source kind*

A kind is a plugin object the **spec module runs**; the kind only knows how to ask for a
location, fetch, check, and connect. The spec module owns the source records, the tree, the
write, the task, the undo entry and the freshness banner — so a second kind (SharePoint, a
URL, Google Docs) is a fetcher and a dialog, nothing else.

*(review)* The contract is **consumer-owned**: a `Protocol` in the spec module's Qt half,
satisfied structurally by `SpecConfluenceModule` (no import in either direction), handed in
by the composition root as `SpecDeps.kinds` — CLAUDE.md rule 3, `project_editor/drops.py`'s
`CanvasDrop` is the worked example. Nothing in `framework/` consumes it, so it does not go
there. The Qt-free *shapes* sit in `domain/` because the spec module's headless core reads
them and the Confluence module's headless half constructs them (the `domain/assets.py`
`AssetSource` precedent).

**`src/dplanner/domain/document_source.py`** (Qt-free)
```python
type Locator = Mapping[str, str]       # kind-specific, JSON-safe: {"site": …, "id": …, "type": "page"|"folder"}

@dataclass(frozen=True)
class FetchedImage:    data: bytes; filename: str          # suffix from the sniffed type
@dataclass(frozen=True)
class FetchedDocument:
    key: str            # the kind's stable id for this page ("12345")
    parent_key: str     # "" for the root
    title: str
    markdown: str       # images linked as assets/<sha16><suffix>, named with domain.assets.asset_name
    version: str        # the kind's stamp ("7"); compared, never interpreted
    url: str            # where a person opens it; https only, validated by the kind
@dataclass(frozen=True)
class Snapshot:
    documents: tuple[FetchedDocument, ...]   # fetched (new or changed)
    kept: tuple[str, ...]                    # keys whose known version matched: keep the row and its images
    images: tuple[FetchedImage, ...]
    notes: tuple[str, ...]                   # what was skipped and why (a whiteboard, an oversize file)
@dataclass(frozen=True)
class Freshness:       changed: tuple[str, ...]; added: tuple[str, ...]; removed: tuple[str, ...]
class SourceUnavailable(Exception):
    needs_reconnect: bool                    # 401: the credential is gone; anything else: try later
    # message is user-facing and never carries a secret or a raw library error
```

**`src/dplanner/modules/spec/source_kind.py`** (Qt; the Protocol)
```python
type Progress = Callable[[float], None]   # TaskRunner.report_progress; there is no message channel (review)

@dataclass(frozen=True)
class SourceStatus:  ready: bool; message: str; connect_label: str   # "Connect to Confluence…" / "Reconnect to Confluence…"

class DocumentSourceKind(Protocol):
    id: str                                   # "confluence" — also the index's source `kind`
    label: str                                # "Confluence Page or Folder…" — the + menu entry
    icon: Callable[[str | QColor], QIcon]     # one painter for the menu (QColor) and the row (str)
    config_changed: Signal[()]                # after connect / forget; hosts re-ask status and context.refresh()
    def locate(self, parent: QWidget) -> tuple[str, Locator] | None: ...   # the URL dialog; validates, no network
    def status(self, locator: Locator) -> SourceStatus: ...   # GUI thread, called from action state: NEVER touches the keychain
    def connect(self, parent: QWidget, locator: Locator) -> bool: ...      # the guided dialog; True when stored
    def open_url(self, locator: Locator) -> str: ...
    def fetch(self, locator: Locator, known: Mapping[str, str], progress: Progress,
              cancelled: Callable[[], bool]) -> Snapshot: ...            # BLOCKING, worker thread
    def check(self, locator: Locator, known: Mapping[str, str]) -> Freshness: ...   # BLOCKING, worker thread, no bodies
```

### 2.2 Index format 4 (`modules/spec.json`)

Additive keys; bump so an older build refuses to rewrite rather than drop them (the
`_to_format_2` precedent). Migration 3→4 is the identity copy (it also re-stamps step
entries, the same one-time churn format 3 caused).

```json
{
  "sources": [
    {"id": "src1", "kind": "confluence", "title": "Auth Overview",
     "locator": {"site": "https://acme.atlassian.net", "id": "12345", "type": "page"},
     "fetched": "2026-09-07"}
  ],
  "documents": [
    {"name": "auth-overview", "title": "Auth Overview", "filename": "auth-overview.md",
     "kind": "markdown", "file": "documents/3fa1….md", "previous": "documents/9c11….md",
     "imported": "2026-09-07",
     "source": "src1", "key": "12345", "version": "7", "parent": ""},
    {"name": "token-lifecycle", "title": "Token lifecycle", … "source": "src1",
     "key": "12346", "version": "3", "parent": "auth-overview"}
  ],
  "assets": [ … unchanged … ],
  "format": 4
}
```
- `source` names the source record *(review: not `origin`, which is the change-origin
  vocabulary everywhere else)*; **absence means project-owned and editable** — no new key in
  front of any existing reader. `key`/`version` are the kind's own strings. `parent` is the
  parent *document name*; sibling order is list order (pre-order), so the tree is derived and
  nothing positional is stored.
- `title` is display; `name` stays the stable identity citations key on. A page's name is
  minted once (`slugify(title)`, deduped `-2`, `-3` — a three-line loop, no helper exists)
  and **kept across refreshes even when the title changes**; the page is matched by
  `(source, key)`. Legacy rows read `title = name`. `matching_documents` gains `title` in
  both the exact and the partial match so `spec show 'Auth Overview'` resolves.
- Blobs are unchanged: `documents/<sha16>.md` for the page markdown, `assets/<sha16><suffix>`
  for its images — the very files `MarkdownView`, `spec show`, the asset catalog, the
  briefing and the coverage trace already read. Nothing downstream learns anything;
  `_coverage_trace`/`anchor_sources` are flat by name and nesting is invisible to them.
- Error state and the last check result are **never in the plan** (per-window memory, §2.5).
  Credentials: OS keychain (§4).

### 2.3 The spec module runs a source

**`modules/spec/sourced.py`** — new, Qt-free, in `HEADLESS_FILES` *(review: not
`sources.py`, which would sit beside the Confluence module's `source.py`)*:
- `SpecSource` dataclass lives in `documents.py` with the index read/write
  (`SpecIndex.sources`); `sourced.py` holds the operations.
- `apply_snapshot(area, index, source, snapshot, today) -> (SpecIndex, Applied)` — **the one
  place the three-way partition lives**: a key in `snapshot.documents` → `attach_asset` its
  images, then `import_document(...)` under the existing name for that key or a fresh one
  (`added` / `replaced` / `unchanged` come from `import_document`'s own outcome, never from
  version comparison; `previous` pinned, `spec diff` per page for free); a key in
  `snapshot.kept` → keep the row; anything else → `remove_document` (blobs stay). Then
  `referenced_assets` in the same index (as `_flush_edit` does) and `fetched = today`.
  Returns counts for the notice.
- `remove_source(index, source_id)`: the source and every document with that `source`.
- `tree(index) -> list[Row]` (name, depth, source or None): the one nested order the tab and
  `spec list` share.
- `owned_by_source(index, name) -> SpecSource | None`: the refusal both surfaces use.
- `attach_asset` in `documents.py` starts delegating to `domain.assets.attach` so the kind's
  `asset_name` and the spec's write are one implementation, not two that agree by
  coincidence *(review)*.

**`modules/spec/module.py`**: `SpecDeps.kinds: Sequence[DocumentSourceKind]`,
`SpecDeps.tasks: TaskService` (the `GithubDeps.tasks` precedent). `register()` adds:
- one `ActionSpec` per kind, `spec.add_source.<kind>`, menu `Project`, group `documents`,
  `submenu="Add Spec"`, label `kind.label`, icon `kind.icon`, `state=_on_a_project` (a pure
  function of the context; it never asks `status()`). Run: `kind.locate(parent)` → one
  `SetModuleDataCommand` adding the source ("Add Confluence Source") → open the tab on the
  source row → if `status(locator).ready`, start the first fetch; else the strip shows Connect.
  `spec.new` and `spec.add` gain `submenu="Add Spec"` too; `spec.new` is both the button's
  face and the first entry of its own dropdown (`report.html` in File ▸ Export does the same).
- `spec.refresh_source` (enabled when the selection is inside a source; greyed label carries
  `status().message`, e.g. "Refresh — connect to Confluence first"), `spec.remove_source`
  (confirm; one command, documents go with it), `spec.open_source` (browser through one
  module-level `open_url` seam, which `spec.open_external` also starts using).
- **Both Refresh and Remove Source call `undo.break_coalescing()` before the push** *(review)*:
  `SetModuleDataCommand.merge_with` coalesces same-label writes and toolbar buttons are
  `NoFocus`, so two Refreshes would otherwise become one undo entry. No `view_origin`: the
  tree must repaint on its own write (`spec.add`'s shape).
- Subscribes to every kind's `config_changed` → `context.refresh()` so the greyed Refresh
  re-reads status where it stands (the marks / theme-toggle pattern).

**`modules/spec/refresh.py`** — new, one `QObject` mirroring `github/refresh.py`'s
`PrRefresher` *(review: one class, same file name as the precedent)*: a `TaskRunner` keyed
`spec.source`, a stoppable first tick, `fetch()` snapshots the known versions on the GUI
thread, runs the kind's blocking `fetch` on the worker, catches `SourceUnavailable` in the
body and reports it on **its own queued signal** (the runner's `failed` carries only
`str(exc)` and would lose `needs_reconnect`), re-checks the source still exists, then applies
**one `SetModuleDataCommand` on the undo stack** — a person pressed Refresh, the Compile Docs
precedent (`docs/module.py`), not the PR refresher's off-stack write. The result reaches the
strip through a `core.signals.Signal` on the refresher, never by polling.

### 2.4 The Specs tab

`activity.py`: the `QListWidget` becomes a `QTreeWidget` (the codebase's one tree idiom;
`TwoLineDelegate` works on it — `setData(0, role, …)` takes a column, give the tree an
object name and a QSS rule since only `#IndexTree` is styled, copy `index_panel.py`'s
`setHeaderHidden`/`setUniformRowHeights`). Order: the pinned Topology row; project-owned
documents; then each source as a top-level row wearing the kind's icon and title, its pages
nested by `parent`. Selection publishes `spec_document` (a page) and/or `spec_source`
(`publish_selection` takes a tuple; `selected_entity(kind)` picks by kind). *(review)* Add a
`rows() -> list[tuple[name, depth]]` accessor and `select_document` over it; the 25
`activity.list.item()/count()` call sites across four test files move onto it.

The reader gains a **source strip** above the document strip, shown for any row inside a
source, mirroring the document strip's idiom: kind icon · "from Confluence · fetched 7 Sep ·
12 pages" · *Open in Confluence* · *Refresh* (registry-rendered through `ActionToolbar`, so
greyed-with-reason is automatic) · and, when `status().ready` is false, the surface's one
primary button labelled `status().connect_label` with `status().message` beside it as an
`#InspectorNote`. The strip also carries the freshness note ("3 pages changed in
Confluence") from the refresher's memory. The source row shows the root page below the strip
(page root) or "Folder · 12 pages — pick one" (folder root); a never-fetched source shows
"Not fetched yet".

**A sourced document is read-only**: `_show_document` routes a `source` document to
`MarkdownView.show_markdown(body, [area])`, never to the editing session. Links between
sibling pages are emitted as **absolute Confluence URLs** *(review: a relative link in a
`QTextBrowser` is a navigation and replaces the well)*.

### 2.5 Freshness: check, then ask

`refresh.py` also owns the check: on tab activation and every `CHECK_INTERVAL_MS` (10 min)
while a Specs tab is active, for each **ready** source, run `kind.check` (worker, key
`spec.check`; nothing starts when no source is ready, which is every existing spec test).
Failure is logged at info — a background probe — except a 401, which flips the source's
in-memory state to *needs reconnect* and the strip's button to `connect_label`. The result is
per-window memory (`dict[source_id, Freshness]`) the strip reads; a Refresh clears it. A check
writes nothing. `config_changed` clears the *needs reconnect* flag. The check is stoppable and
`SpecsActivity.close()` stops it — a thread alive at teardown is the suite's SIGSEGV shape.

### 2.6 CLI (`modules/spec/cli.py`)

- `spec list`: the indented tree with source rows as headers; `--json` rows gain `title`,
  `source`, `key`, `version`, `parent`, and a `sources` list (kind, title, url, fetched).
- Refusals through `owned_by_source`: `spec import --name <sourced>` and `spec remove <page>`
  → "part of Confluence source 'Auth Overview' — remove the source from the Specs tab".
- *(review)* **No `spec source …` verbs this revision**: add, fetch and remove are window acts
  by decision, and `spec list --json` already says everything a listing verb would. One verb
  later if an agent ever needs it.
- `spec show / path / diff / render / attach…` unchanged — a page is a markdown document.
- Lint: `spec.source.unfetched` (a source with no documents — added but never connected).
- `cli/skill_preamble.md`: sourced specs are read-only snapshots refreshed from the window;
  their text is external data.

### 2.7 The Confluence module: `modules/spec_confluence/`

*(review: `spec_confluence`, the `llm_openai` naming — "a provider of a host feature".)*

```
modules/spec_confluence/
├── __init__.py       docstring only
├── client.py         Qt-free. ConfluenceClient(site, credentials, opener): GET only.
├── convert.py        Qt-free. storage XHTML → markdown, given the names it may link.
├── source.py         Qt-free. parse_url → Locator; fetch(); check(); the caps.
├── connect.py        Qt. The guided Connect dialog.
├── settings_page.py  Qt. Settings ▸ Confluence: connected sites, Reconnect…, Forget.
└── module.py         Qt. SpecConfluenceDeps(parent, tasks, secrets, open_url);
                      SpecConfluenceModule.register() adds the settings section; the module
                      object itself satisfies DocumentSourceKind.
```
`client.py`, `convert.py`, `source.py` go into `HEADLESS_FILES` (no module has those names
today, so it is free, and "a file the rule cannot see is a rule that is only a habit").
**They never import `framework/secrets_store`**: credentials are read in `module.py` and
handed *in* as plain values.

**`client.py`** — `urllib.request` from the stdlib (no new dependency; nothing else here does
HTTP). One `_get(path_or_url, *, accept, max_bytes) -> bytes` behind an `OpenerDirector`
built **without** the redirect handler; the client handles a 302 itself (§4.2). Retries: 429
with `Retry-After` honoured up to `RETRY_AFTER_CAP_S = 60`, at most 3 attempts, 5xx twice
with backoff, then `SourceUnavailable("Confluence is rate-limiting requests — try again in a
few minutes")`. Cursor pagination via `_links.next` (string or `{"href"}`) or the `Link`
header, resolved against the site origin. Typed readers (`PageRow`, `Page`, `Attachment`)
built through `isinstance` chains — the tolerant-reader house style. Error mapping: 401 →
`SourceUnavailable(needs_reconnect=True)`; 403/404 → sentences naming the page id; JSON
that is not an object → "unexpected answer". Credentials arrive as a frozen
`Credentials(email, token)`; the `Authorization` header is built per request from them and
this is the only code that ever sees the token.

**`convert.py`** — `html.parser.HTMLParser` subclass (no entity/DTD expansion, no network;
namespaced tags arrive as ordinary names `ac:image`). Handlers for §1's elements;
`unknown_decl` collects CDATA. Contract: `convert(storage_xhtml, images: Mapping[filename,
asset_name], pages: Mapping[title, url]) -> str` — the caller passes the names it will write
and the sibling URLs, so output links `assets/<sha16>.png` and absolute page URLs. Output
invariants (tested): no raw HTML (`<` in text is escaped), only `http(s)`/`mailto` absolute
links, only `assets/…` names that were in the map, unknown macros become
`> **Confluence macro `jira` — not exported**`. Depth-guarded, never recursive on input.

**`source.py`** — `parse_url(text) -> (title_hint, Locator)` for
`…/wiki/spaces/<KEY>/pages/<id>/<slug>`, `…/wiki/spaces/<KEY>/folder/<id>`,
`…/wiki/pages/viewpage.action?pageId=<id>`; the short `…/wiki/x/<code>` form is refused with a
sentence; the host must match §4.2's pattern. `fetch()` walks `direct-children`
breadth-first, skips `status != current` and non-page/folder types (noted), caps
`MAX_PAGES = 500` and `MAX_DEPTH = 20`; a page whose `version` equals the known one goes into
`kept` without a body request (its images cannot be re-named without their bytes — the one
reason `kept` exists); otherwise it fetches the storage body and attachment list, downloads
only attachments the body references by filename and only raster images (sniffed magic:
PNG, JPEG, GIF, WebP; ≤ 20 MB each, ≤ 200 MB per fetch), names them with
`domain.assets.asset_name`, converts, and returns a `Snapshot`. `check()` = descendants +
bulk pages by id, compared with the known versions. Cancellation is polled between requests.

**`connect.py`** — `ConnectDialog(parent, locator, *, tasks, test)`: Site (read-only),
Email, API token (password echo, never logged). A numbered guide: 1 "Open Atlassian API
tokens" (a button through the `open_url` seam →
`https://id.atlassian.com/manage-profile/security/api-tokens`), 2 "Create API token" — a
classic token; scoped tokens are not yet supported, and the token expires within a year, so
you will be back here, 3 paste. *Test connection* runs `GET /wiki/api/v2/pages/{root}` (or
`/folders/{root}`) on a **`TaskRunner(tasks, parent=dialog)`** keyed `confluence.test`
*(review: not a `_ModelLoader` clone — CLAUDE.md says every hand-written thread goes through
`TaskRunner`)*, and reports the title or the mapped error. OK is enabled only after a
passing test; OK stores the token through the module's `secrets` seam and the site→email row
in `user_config`, then the module emits `config_changed`. If the secret store reports a
backend problem (§4.1), the dialog says so and stores nothing.

**`settings_page.py`** — Settings ▸ Confluence: the `user_config` rows (site, email) with
*Reconnect…* and *Forget* (delete the secret and the row; `config_changed`).

**`module.py`** — `SpecConfluenceDeps(parent, tasks: TaskService, secrets: SecretStore,
open_url)`. `SecretStore` is a four-callable protocol the root wires from
`framework/secrets_store` *(review: so tests hand in a dict and never touch a real
keychain — nothing in the suite does today)*. `status(locator)` derives `ready` from the
`user_config` site→email row **and never reads the keychain** — it runs inside action
`state`, on every context change, and `keyring.get_password` is a D-Bus round trip that can
raise an unlock prompt. The token is read only inside `fetch`/`check`/`test`. A 401 reported
by the refresher makes `status()` answer "acme.atlassian.net rejected the token — it may
have expired (tokens last at most a year)" with `connect_label = "Reconnect to Confluence…"`
until `config_changed`.

### 2.8 Composition root

`modules/__init__.py`: construct `SpecConfluenceModule` before `spec` and hand it in through
a `_source_kinds(...)` helper (the `_asset_sources()` shape — also the test seam, §3):
`SpecDeps(kinds=_source_kinds(confluence), tasks=services.tasks, …)`. List it in
`default_modules()` before `spec` with the position comment. `default_module_formats()` is
unchanged (spec's format rides on its aspect). CLI: `spec_cli.commands(...)` signature
unchanged; lint gains the new check through `spec_cli.lint_checks()`.

---

## 3. Files to change / add

**Domain and framework**
- `src/dplanner/domain/document_source.py` — new (§2.1 shapes).
- `src/dplanner/domain/store.py` — `ModuleFileArea` refuses a name that is absolute, has a
  backslash or a `..` segment, on **every** `_join` path (`read_bytes`, `write_bytes`,
  `absolute`, `remove`): `MarkdownView.loadResource` already hands pasted-markdown names to
  `read_bytes`. Domain, so no `NOTES-FOR-APPFRAME.md` entry.
- `src/dplanner/framework/secrets_store.py` — `backend_problem() -> str | None`: probes
  `keyring.get_keyring()`; `fail.Keyring`, a `keyrings.alt` (plaintext) backend, or a
  `KeyringError` → a sentence naming the platform's remedy (§4.1). **Record in
  `NOTES-FOR-APPFRAME.md`.**

**Spec module**
- `modules/spec/documents.py` — `SpecDocument` gains `title`, `source`, `key`, `version`,
  `parent`; `SpecSource`; `SpecIndex.sources`; format-4 read/write; `matching_documents`
  matches `title`; `attach_asset` delegates to `domain.assets.attach`.
- `modules/spec/aspect.py` — `DATA_FORMAT` → 4 with `_to_format_4` identity.
- `modules/spec/source_kind.py` — new (§2.1 Protocol, `SourceStatus`, `Progress`).
- `modules/spec/sourced.py` — new, Qt-free (§2.3); in `HEADLESS_FILES`.
- `modules/spec/refresh.py` — new (§2.3, §2.5).
- `modules/spec/module.py` — deps, the submenu actions, refresh/remove/open verbs,
  `open_url` seam, `break_coalescing`, `config_changed` → `context.refresh()`.
- `modules/spec/activity.py` — tree + `rows()`, source strip, read-only route, `spec_source`
  selection, `TOOLBAR_ACTIONS` loses `spec.add` (it is a menu entry now), stale
  `_retitle_tabs` comment goes.
- `modules/spec/cli.py` — `spec list` tree/JSON, refusals, lint.
- `cli/skill_preamble.md` — the sourced-specs paragraph.

**Confluence module** — the seven files in §2.7.

**Composition root** — `modules/__init__.py` (§2.8).

**Docs** — `CLAUDE.md` (two bullets: *A spec source is a kind the spec module runs*; *An
external source's credential is the person's, never the plan's*), `ARCHITECTURE.md` (why the
spec module runs the kind rather than the kind writing the index; why Refresh is on the undo
stack while a check writes nothing; why fetching is window-only; read-only by construction;
the egress rules; why `status()` never touches the keychain), `FORMAT.md` (format-4 shapes;
the keychain row gains the Confluence entry `confluence.token:<site>`), `README.md` (layout
map: `spec_confluence/`, `spec/`'s line), `NOTES-FOR-APPFRAME.md` (`backend_problem`).

**Tests**
- `tests/modules/test_confluence_client.py` — Qt-free, a `FakeOpener` routing table that
  **raises on any method but GET**: pagination (Link header and `_links.next`, string and
  dict, relative `/wiki`), 429 + Retry-After and the cap, 401 → `needs_reconnect`, 403/404
  sentences, a cross-host 302 followed once without the Authorization header and refused for
  http / a foreign host, the read cap, non-object JSON, the token never appearing in any
  exception text.
- `tests/modules/test_confluence_convert.py` — storage fixtures as inline strings:
  headings/lists/tables/code (CDATA, spaced `]] >`)/panels/tasks/layouts/mentions/time/
  emoticons/status; images by attachment (mapped and unmapped) and external; sibling and
  stranger page links; the hostile set — `<script>`, `<iframe>`, `javascript:`/`file:` hrefs,
  raw `<img src=http>`, an entity bomb, 10 000-deep nesting, a filename `../../x.png`, an
  unknown macro.
- `tests/modules/test_confluence_source.py` — Qt-free: `parse_url` forms and host refusal;
  the walk with folders and skipped types; the caps; `kept` on an unchanged version; image
  filtering by reference, sniffed type and size; asset names equal `asset_name(bytes, …)`;
  cancellation between requests.
- `tests/modules/test_spec_sources.py` — GUI with a **fake kind**: a `fake_kind(monkeypatch)`
  fixture **listed before `services`** that patches the root's `_source_kinds` (fixture order
  is the seam; say so in its docstring). Cases: the + dropdown lists kinds via
  `toolbar.menu_for("spec.new")`; add → source row → Connect button when not ready →
  `config_changed` → button gone; fetch applies as one undo entry and nests pages (wait for
  the worker with `test_github_refresh.py`'s `wait_for` loop — never `qtbot.wait` for the
  tree); a sourced row opens read-only; Refresh replaces changed pages only, keeps
  `previous`, and two Refreshes are two undo entries; Remove Source takes the subtree and
  undoes; the freshness note appears from a canned `Freshness` and clears on Refresh; a check
  writes nothing; a 401 flips the button label; the check stops on close.
- `tests/modules/test_confluence_connect.py` — the dialog (disposed with `deleteLater`): OK
  disabled until a passing test; the token reaches the injected secret store and never
  `user_config`; a backend problem refuses; the browser button goes through the seam.
- `tests/cli/test_spec_sources.py` — Qt-free: format 3→4 migration; `spec list` tree and
  JSON; the refusals; the lint check.
- Update `tests/modules/test_spec.py` (toolbar shape, `rows()`), the three sibling spec test
  files (`rows()`), `test_spec.py`'s stale docstring path, and `tests/test_architecture.py`
  (`HEADLESS_FILES` gains `sourced.py`, `client.py`, `convert.py`, `source.py`).

---

## 4. Security decisions (what to hold the implementation to)

### 4.1 The credential

1. **Only in the OS keychain**, through `secrets_store` as `("confluence", f"token:{site}")`;
   the site→email row in `user_config` is the *fact that a site is connected* and what
   `status()` reads. Never in `spec.json`, the file area, telemetry, a task label, a log line,
   a `SourceUnavailable` message, the briefing or the skill. Error text is composed from
   status codes and our own sentences, never `str(exc)` of a urllib error.
2. **Per platform** (`keyring>=25`, already a dependency): macOS → Keychain (the first store
   may show the system's "dplanner wants to use your keychain" prompt — say so in the guide);
   Linux → Secret Service (GNOME Keyring, KDE Wallet via `secretstorage`) — on a bare window
   manager with no daemon `keyring` selects `fail.Keyring`, and `backend_problem()` turns that
   into "No keychain service is running — install and unlock GNOME Keyring or KWallet, then
   connect again"; Windows → Credential Manager (`WinVaultKeyring`, bundled). **Never a
   plaintext fallback**: a `keyrings.alt` backend is refused by name even if installed. The
   dialog refuses to store rather than storing nowhere silently (the current `set_secret`
   swallows the error; that stays for the LLM keys but Connect checks first).
3. Tokens expire within a year: the 401 → *Reconnect* path is a normal flow with the same
   dialog, and the settings page lists what is connected so a token can be forgotten.

### 4.2 Egress

4. The locator's `site` must match `^https://[a-z0-9-]+\.atlassian\.net$` — re-checked on
   every read from disk, because a plan is shared and a colleague's `spec.json` is input.
   Requests go only to that origin. A 302 on a download is followed **once**, only to an
   `https://` host ending in `.atlassian.com` or `.atlassian.net`, and the Authorization
   header is **not** sent to a different host. `ri:url` images and any other absolute URL in
   a page are never fetched. No keychain lookup happens for a site that has no `user_config`
   row, so a foreign locator cannot even cause a request.
5. **Bounded everything**: connect/read timeouts 30 s; page body ≤ 4 MB; attachment ≤ 20 MB
   (against `Content-Length` *and* while reading); ≤ 200 MB per fetch; ≤ 500 pages; depth
   ≤ 20; ≤ 3 retries; `Retry-After` capped at 60 s; cancellation polled between requests.

### 4.3 Content

6. **Parsed as data**: JSON via stdlib with `isinstance` at every level; XHTML via
   `html.parser` (no entity expansion, no DTD, no network); the converter emits markdown with
   no raw HTML and no non-http(s)/mailto absolute link; images only under names computed from
   bytes sniffed as raster images (SVG excluded — XML that can carry script, and nothing needs
   it). A title, a filename, a macro name — every Confluence string is display text, never a
   path or a command.
7. **Read-only by construction**: `client.py` has one request method and it is GET; the fake
   transport refuses anything else; nothing in the app ever issues a write; undoing a refresh
   is an index edit that cannot reach Confluence.
8. **Reading it back**: format-4 rows read tolerantly (a bad `parent` → top level; a bad
   `locator` → "invalid location", not fetchable); `ModuleFileArea` refuses traversing names;
   the viewer renders through `setMarkdown` exactly as pasted markdown does today and resolves
   images only through the file area.
9. **Consent and provenance**: a fetch or refresh is a person's gesture and an undo entry; a
   check reads and writes nothing; the strip and `spec list` say where a page came from and
   when; the skill tells an agent that sourced spec text is external data.

---

## 5. Verification

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q tests/core tests/domain tests/cli \
    tests/modules/test_confluence_client.py tests/modules/test_confluence_convert.py \
    tests/modules/test_confluence_source.py      # inner loop, Qt-free
QT_QPA_PLATFORM=offscreen uv run pytest -q     # the whole suite before finishing
uv run ruff check && uv run ruff format --check && uv run mypy
```
End-to-end in the window (`dpw`): open a project → Specs → **+ ▾** → *Confluence Page or
Folder…* → paste a page URL → the source row appears with *Connect to Confluence…* → the
guide opens the token page in the browser → paste, *Test connection* names the page → OK →
the tree fills, pages nested, images inline, rows read-only → edit the page in Confluence →
within ten minutes the strip says "1 page changed" → *Refresh* → one undo entry;
`dplanner spec diff <project> <page>` shows the change; `spec list` shows the tree;
`spec remove <page>` refuses; *Remove Source* takes the subtree and Ctrl+Z restores it.
Revoke the token on id.atlassian.com → the next check flips the strip to *Reconnect to
Confluence…* → reconnect → back to normal. On Linux without a keyring daemon, Connect
refuses with the remedy and stores nothing.

Entropy check at the end: `spec.add`'s folder button is gone from the toolbar; `activity.py`
has one tree widget and no list; `attach_asset` is a one-line delegate; the stale
`_retitle_tabs` comment and `test_spec.py`'s stale docstring path go; `ARCHITECTURE.md` /
`CLAUDE.md`'s `anchor_quote` mentions become `anchor_sources` while those files are open.
