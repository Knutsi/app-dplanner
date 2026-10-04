# Specs — the spec editor and its document sources

The reasoning behind `.claude/rules/specs.md`: the rules there are the short, imperative form, and this file is why. `ARCHITECTURE.md` is the index of every area.

## Editing a spec in-app is a replace

The Specs tab can author a markdown document, not just import one, and the editor had to
answer the question every document editor faces here: spec bodies are content-addressed
blobs in a file area — outside the model, outside the undo stack, outside autosave. The
answer is that **an editing session is one replace**, the same operation `dplanner spec
import` performs on an existing name, so the CLI needed no new editing verb and the two
surfaces still speak one vocabulary.

Concretely: a markdown document has no read mode — picking its row opens it in the
editor, and that is the session's start; picking another row, or closing the tab, is its
end. The editor flushes on the autosave rhythm (a pause in typing) and at those boundaries,
and every flush writes a new blob and pushes the index update as a `SetModuleDataCommand`
with one label — command merging turns however many flushes into a single undo entry, and
`previous` stays pinned to the blob that was current when the row was picked, so `spec
diff` answers "what did this session change". Undo restores the pre-session index, and the
pre-session blob is still on disk — the same invariant every replace relies on. There was
a *Done* once, and an *Edit Spec Document* verb to reach the editor: a read mode nobody
wanted for text they came to write, and a button whose absence a reader took to mean
"unsaved". Both went; the idle flush was always what persisted. The one carve-out from "orphans are never pruned": a blob the session
itself wrote and then superseded is churn, not history, and is removed once nothing in the
index names it (`prune_blob`). Typing inside the editor is the widget's own undo stack;
the application stack holds only the session-level replaces — two stacks because they hold
two different kinds of fact, keystrokes and index states.

**The editor is the prose stack's, and two of those three edges went with the widget.**
It was a `QTextEdit` over `setMarkdown`/`toMarkdown` — the one prose surface in the
application that edited a document *tree* and wrote back a normalised serialisation, which
is precisely what `framework/markdown_highlight.py` says a markdown editor here must not
do. It is a `ProseEdit` now, with the highlighter, the markdown strip, and the figures it
links to in a gallery under it, because a plain-text editor cannot draw a picture and
should not pretend to. What that deleted: the standing warning that editing would reformat
the document (plain text never reformats, so an untouched save is byte-identical by
construction rather than by a guard), the `![](` → `![image](` rewrite on open (Qt's
exporter dropped an empty alt; there is no exporter), and the carve-out that made a `.txt`
read-only — its whole reason was the round-trip handing it back as markdown. A PDF is the
one document that is not text, and renders.

There was a correctness fix hiding in that swap. `document_text()` — what `feature cite`,
lint, coverage and `anchor_in` all read — is the raw markdown **source**, while the
rich-text editor's `toPlainText()` was the **rendered** text. So citing a heading, or any
passage with inline markup in it, stored one string while every other reader checked
another; they agreed for plain paragraphs and disagreed silently everywhere else. The
editor's string is now the string every reader uses.

**A foreign change to the edited document ends the session** and reopens the document as
it now is: the model is the authority, unflushed keystrokes yield, and anything already
flushed survives as a recoverable blob. An agent replacing the document under an open
window resolves through *Two writers, one folder* like every other write.

**Expanding it is the same buffer, not a second binding.** The dialog's other path
(*Expanding an editor is a second binding, not a copy*) opens a `TextField` twice, because
there the model is the authority and each view hears the other's commands as foreign. Here
the *buffer* is the authority until the flush, so `over_document` hands the dialog the
inline editor's own `QTextDocument`: one buffer, two views, one undo history, in step by
construction. That is the base case of "never copy text out and back", and the binding pair
is the derived one. The alternative — a `TextField` adapter over the session buffer — would
have had to push a command per keystroke onto the application's undo stack, which is the
one thing the two-stacks rule above exists to prevent. The price is a Qt fact worth
knowing: when the borrowing view dies, the owner's *Python wrapper* for the document is
invalidated even though the C++ document and its text survive, so nothing may hold
`editor.document()` in a field. `NOTES-FOR-APPFRAME.md` §36 has the measurements.

**A rename moves the name, and everything that points at it.** There was no rename at all,
and a name is the one thing an agent types: `spec show`, `spec diff`, `feature cite
--document`, the `document` key on every passage a feature cites. Two shapes were on the
table. Rename only a *display title* and leave the key alone — which is what a sourced page
already does, and which cannot break anything — or move the key and carry its references.
The first was rejected for the reason the step existed: a key that no longer describes the
document is exactly what misleads the next agent, and a title beside a stale key leaves the
misleading thing in place and adds a second name to learn. So the key moves, and with it
the pages that name it as their parent, the asset rows that record where a figure came
from, and every feature step's citations — the last of which is another module's data, so
the composition root walks the steps, composes the commands, and both surfaces push them
inside one `CompositeCommand`. The filename's stem follows too, keeping its suffix: it is a historical
fact, but `matching_documents` resolves a needle against it, so leaving it behind would let
the old name go on addressing a document somebody had just renamed. What does *not* move is
the blob, which is content-addressed and never carried the name.

The honest cost is written down here because nothing can fix it: prose cannot be carried.
A note, a description or an agent's own memory that named the old key is stale after a
rename, and no command can find those. That is the trade the decision accepts — a stale
sentence is a thing a person reads and corrects, where a stale *key* is a citation that
silently stops resolving.

**Delete takes the index row and never the blob.** Four reasons, any one sufficient: undo
would restore a row pointing at nothing; blobs are content-addressed and therefore shared,
so deleting "the file" can pull the bytes out from under a second document with identical
content; `previous` is a second pointer at the same place, and `spec diff` reads it; and
`FORMAT.md`'s rule is that an orphaned blob is recoverable where a dangling link is not,
with the editing session's own churn as the single named carve-out. The workspace's git is
the history that makes leaving it cheap.

**The mark on the tab title is what this window has found.** `updates_words` — written and
tested when the sources landed, and uncalled until now — is the line over the whole tree,
where it is true whatever row is picked; its short form marks the tab's title and the Specs
row in the index, so there is something to see before the tab is opened. One `stale`
derivation, three readings. It rides a **set-diff** signal rather than the refresher's own
`changed`, which also fires on every busy flip and would redraw the index folder on each
spinner tick. And checking follows whether a Specs tab is **open**, not whether it is the
pane in front — the active-pane rule is about publishing a selection, and a mark that only
lit while you were already looking at it would say nothing. The scope that stays is the
honest one: a project whose Specs tab nobody has opened is not being checked, and wears no
mark. Checking every source of every project on a timer would mean a `git ls-remote`
subprocess per source per interval on a machine nobody asked, for a dot on a row.

## A spec source is a kind the spec module runs

The spec was always a file somebody put beside the project. Now it may live somewhere
else and change there — a folder on this computer, a git repository, a Confluence page, a
Confluence folder — and the question was where the machinery for that belongs. Two shapes were on the table: each
source module owns its own tree, task and index writes and the spec module hands it a
writer seam; or the spec module runs every source and a source module is nothing but a
*kind* — how to ask for a location, whether it is connected, how to connect, how to fetch
and how to check. The second won, for the reason the asset catalog and the report
sources did: the interesting logic (records, nesting, the write, the undo entry, the
freshness note, the strip) is the same for every source, and writing it once in the
consumer is what makes the second kind a fetcher and a dialog. The contract is a
`Protocol` in `modules/spec/source_kind.py`, consumer-owned like `CanvasDrop`; each kind
module satisfies it structurally and the composition root hands the kinds in as
`SpecDeps.kinds`. The four that shipped are the proof it was the right split: the folder
kind is a hundred lines over a shared walk, and the git kind — by far the largest — adds
a subprocess door and a dialog and changes nothing in `modules/spec/`. The Qt-free shapes they exchange — `Snapshot`, `FetchedDocument`,
`Freshness`, `SourceStatus`, `SourceUnavailableError` — sit in
`domain/document_source.py`, beside `AssetSource`, because the spec module's headless
core reads them and the kind's headless half constructs them and neither may import the
other.

**A fetched document is an ordinary spec document.** It arrives as **bytes and the
filename it had where it came from** — markdown, plain text or a PDF — and lands as a
content-addressed blob under `documents/` whose *stem is the name the spec module minted*
and whose *suffix is the kind's*, which is what decides how it is read and what stops a
kind renaming every row of an existing plan by changing its mind about filenames. Its
images are `assets/<sha16><suffix>` in the same area, and
the index row carries what makes it a *sourced* one: `source` (the record), `key` (the
kind's own id for the page), `version` (the kind's stamp, compared and never
interpreted), `parent` (the document above it, by name) and `title`. Absence keeps its
old meaning — a row without `source` is project-owned and editable — so no existing
reader learned a key. The consequence is the one that mattered: `spec show`, `spec
diff`, citations, coverage and the briefing needed no change at all, because
`apply_snapshot` writes every page through the same `import_document` a replace uses, and
a refreshed page therefore keeps `previous`. A page's **name is minted once** from its
title and kept across refreshes even when the title changes — a citation keys on the
name, and a title is a thing people edit — with the page matched by `(source, key)`.

**Refresh lands on the undo stack; a check writes nothing.** A person pressed Refresh
(or added the source), so Ctrl+Z must put the documents back — the Compile Docs
precedent, not the PR refresher's off-stack write, and `break_coalescing()` runs first
because the toolbar's buttons take no focus and two refreshes would otherwise merge into
one entry. The check is the other half of "check, then ask": on the interval, while a
Specs tab shows the project, `check_all` compares versions (two or three requests for a
tree, no bodies) and the strip says "3 documents changed at the source — Refresh"; nothing
is downloaded until the person asks. Both run on `TaskRunner`s in `spec/refresh.py`, the
`github/refresh.py` shape; a refusal that names the credential (a 401) is remembered per
window as *needs reconnect* until the kind's `config_changed` says otherwise. Both
memories are keyed by **(project, source)**: a source id is minted per project, so two
open projects both have a `src1`, and a dict keyed on the id alone had one project's
freshness answering for the other's — invisible while only the selected source was ever
asked, and a wrong number the moment something counts them.

**One kind, one thing — and a kind is a record, not a code path.** The Confluence module
shipped as a single kind whose locator carried `type: page | folder`, so the Add Spec menu
offered one entry for two different acts and a person pasting a folder address into it got
whatever the walk made of it. They are two kinds now, and the interesting part is what did
*not* fork: the walk is still one function, because the only difference between a page
source and a folder source is where the queue is seeded, and that is a branch on a value
the kind has just validated. What forked is data — a frozen `ContentType` with the id, the
words and the content type each kind accepts — and one `ConfluenceKind` class constructed
twice over it, on a module that keeps the client, the credential, the Connect dialog and
the settings page, because connecting to a site serves whichever of the two a source is.
The payoff is a sentence that could not exist before: *that is a folder address — add it
with Add Spec ▸ Confluence Folder*. The same `expected` argument is what stops a
hand-edited plan aiming one kind at the other's locator, which is the reason it is checked
on every read and not only at the door.

**A folder walk is domain's, because two kinds read it and modules never import each
other.** `domain/document_folder.py` sits beside `document_source.py` for the reason
`AssetSource` sits beside the asset catalog. Two decisions inside it are worth the ink. A
**version is a digest over the body and the pictures it links**: the body alone leaves a
document unchanged when a diagram beside it is redrawn, so the row is kept, and the page
goes on showing a blob that is no longer what the author drew — silent, and only visible
to somebody who looks at the picture. And `is_document` is **exported**, because the git
kind's `check` derives the same key set from a git tree without reading a byte; two rules
for what a document is would make a check lie about every file in the gap between them.
The nesting rule — a directory's `README.md` is the parent of its siblings, a directory
without one is transparent — was chosen because it can only *add* structure where somebody
already wrote the page that means it, and degrades to exactly flat otherwise.

**A git source's checkout is the person's cache, and the guard runs before the download.**
The plan is committed and shared, so megabytes of somebody else's repository cannot live
in it; the checkout goes under `config_dir()`, keyed on url + ref + path, one directory
per source — sharing one checkout between two sources would mean one fetch's sparse
pattern applied to the other's tree, which imports the wrong folder and says nothing. The
clone door itself — the blobless, shallow, sparse fetch, the listing, the subprocess
hardening — is `core/storage/sparse.py`'s now, because a project's read-only *locations*
(*A project names its locations*) are placed in the same cache under the same digest, and
a source that names a `spec` row (*Add Spec ▸ From Location…*) resolves to the row's
address at every call, so the row, its managed placement and the source fetched from it
share one directory. The harder question was the size guard. A person pointing at a monorepo must be steered to a
subdirectory *before* they wait for it, and git will not report a blob's size without
fetching the blob — so the guard counts, it does not weigh: `--filter=blob:none` brings
the commit and all its trees and no content, the listing says how many files and how many
documents each folder holds, and an oversized one is refused in the dialog, beside the
folder, while it is being chosen. `GIT_NO_LAZY_FETCH` is set on the listing so an
accidental content read fails loudly instead of quietly downloading the repository behind
the guard's back, and the sparse pattern is written non-cone because cone mode also
materialises every file at the levels *above* the chosen folder — which would make the
guard have measured the wrong thing.

**A git document's version is its blob oid, not the commit.** `Freshness` is per document,
and a commit id moves for every file in the repository: using it would make the tab say
*everything changed* every ten minutes after anybody touched anything. A blob oid is a
content digest git has already computed and hands back from a tree for free, so `check` is
one `ls-remote` and, only when that moved, one blobless tree fetch and a comparison — no
bodies, and an honest answer. What the cache remembers is the last commit taken in, as a
ref inside itself: not the locator (which is shared and would drift per machine), not a
field on the source record (the plan would carry a fact about one person's disk), and not
per-window memory (that is what the last *check* found, which is a different thing). Its
disposability is the point: wipe the cache and the next check pays one tree fetch.

**`locate` may reach the network; what it may not do is block the GUI thread.** The
contract said *no network*, which was the shape that rule took for Confluence, whose
locate is a URL parse and whose network needs a credential only `connect` can obtain. The
git kind's whole reason is *which folder?*, and that cannot be answered without asking the
remote. The alternatives were worse in ways this step was meant to avoid: moving the probe
into `connect()` makes adding a source two gestures, the first of which adds something
that does not work and trips the `spec.source.unfetched` lint; and typing the subdirectory
blind means meeting the size guard as a failed fetch. So the docstring says the rule it
always meant — never block the GUI thread — and the git dialog probes on a `TaskRunner`,
the way the Connect dialog already did.

**One gesture is one undo entry, and the one-source case is not a special case.**
*Refresh All Sources* had two honest shapes: land each source as it arrives (N entries, N
Ctrl+Zs to undo one press) or collect and land together. The second is what a person means
by pressing one button, and `UndoService.gesture` already does it — with the detail that
makes the design cheap: a gesture holding exactly *one* push places that push itself, with
its own label. So `refresh` is `refresh_all` over a list of one, refreshing a single source
writes precisely what it wrote before, and no `if len(...) == 1` appears anywhere. A
source that refuses is skipped inside the gesture and reported after it closes, because a
failure must never cost the sources that succeeded.

**Fetching stays window-only, and the reason changed.** It used to be the credential: the
token is in the keychain, a shell could reach it, and an agent's shell runs with the
person's keychain but not their judgement. A folder source has no credential at all, so
that argument does not reach it. The one that does is simpler and covers all four: a fetch
pulls bytes from outside the plan *into* it, and choosing to do that is a person's act.
`spec list` shows the tree, its kinds and its locators, `spec show` and `spec diff` read
the snapshot, `spec import` and `spec remove` refuse a sourced document with a pointer to
the tab, and adding, refreshing and removing a source are window acts. The LLM service's
rule (*An LLM call is a task*) is the same rule from the other side.

**The credential is the person's, per site, per machine, and `status()` never touches
the keychain.** The token goes through `framework/secrets_store.py` under
`spec_confluence.token:<host>`; the site → email row in `user_config` is *the fact that
a site is connected*. That split is not tidiness: an action's `state` runs on every
context change, and `keyring.get_password` is a D-Bus round trip that can raise a
keychain prompt in the middle of a menu opening. So `status()` reads the row, and the
token is read only inside `fetch`, `check` and the Connect dialog's probe, handed to the
client as a value. The dialog stores nothing until its probe read the page, and refuses
up front when `backend_problem()` says this machine cannot keep a secret — a plaintext
file is never the fallback, which is the lesson `gh auth login` learned in public.
Tokens expire within a year, so *Reconnect* is the same dialog and a normal event.

**Read-only against Confluence by construction, and every byte from it is data.** The
client has one request method and it is GET; the fake transport the tests hand in has no
other verb to call. Requests go only to the source's `*.atlassian.net` origin — the
locator is re-validated on every read from disk, because a plan is shared and a
colleague's `spec.json` is input — and a download's one redirect is followed only to an
Atlassian host, without the credential when the host changes. Bodies, attachment sizes,
page counts, depth, retries and `Retry-After` are all capped. The storage XHTML is parsed
by `html.parser` (no entity or DTD expansion, no network) into a depth-capped tree, and
the markdown it becomes carries no raw HTML, links only `http(s)`/`mailto`, and names only
images the fetch sniffed as raster and content-addressed itself; dynamic macros, whose
content is not in storage, become a labelled placeholder. Every error a person sees is
composed here from the status code — a library's own message is where a credential would
leak into a log.
