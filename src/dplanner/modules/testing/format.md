# How a test is written

The house shape of a test body, followed wherever the project and the person you are
planning with have not asked for another. `dplanner test add` and `dplanner test set`
refuse until this has been read on this machine.

A test is executed by somebody who was not there when it was written — a year later, by a
person with no memory of the work, or by an agent with no context at all. The title is the
claim (*what must keep being true*); the body is how a stranger proves it. So a body is
**what must already be true**, and then **what to do**, under those two headings and in that
order.

## The two headings

```
## Preconditions
- Signed in as a reviewer with signing rights (reviewer@example.com).
- One document in `Ready for signature`, with no signature on it yet.

## Steps
1. Open the document from the review queue.
2. Press **Sign** — the signing dialog opens with the reviewer's name filled in.
3. Confirm. The dialog closes and the document reads `Signed`, with the reviewer's name
   and today's date on the signature line.
4. Reload the page: the signature is still there.
```

**Preconditions are bullets, and each one is a state rather than an action** — the account
and role signed in, the data that has to exist, the flag that has to be on, the window the
run starts from. A precondition nobody can arrange is not one: say how it is reached, or
name the seed, script or fixture that makes it. Leave the heading out only when the test
genuinely starts from nothing.

**Steps are numbered, one action each, in the imperative** — and the last one says what
proves the test passed. Where a step has an observable result of its own, say it in that
same step, the way step 2 and step 3 do above. Never leave the pass condition in a paragraph
after the list: somebody working down a roster reads the numbers.

**One test per thing that can independently break.** A body carrying two *Steps* sections is
two tests; split it, and let each carry its own result in a run.

## Screenshots

A picture belongs in a test wherever words cannot say *what to look at*: which control of
several, which of two similar screens, what wrong looks like beside right.

```
dplanner test attach 'Sign a document' signing-dialog.png   # prints the link to paste
dplanner asset name <project> ab12cd34 'Signing dialog'    # optional: a title for the picture
```

Three rules, and they are what turns a pile of images into a sequence:

- **A picture goes in the step it belongs to, in the order the steps run.** Put the link on
  that step's line rather than collecting the images under the body — the number the step
  already carries is the sequence, and nothing else has to be invented to say what follows
  what.
- **The alt text is the annotation.** `![2 — the signing dialog; Sign stays disabled until a
  name is typed](assets/…)` says which step it belongs to and what to look at in it. A bare
  `![](assets/…)` teaches nothing the picture does not already show.
- **The words still stand without it.** An export renders the link but carries no images, so
  a reader may meet the test with none of them loading. A step whose screenshot is missing
  must still be executable.

In a body that is one step of the sequence and its picture:

```
3. Confirm. The dialog closes and the document reads `Signed`.
   ![3 — the signature line: the reviewer's name and today's date](assets/7c1f2a9b.png)
```

Images live beside the **step**, so every test on that step can reference the same one:
`dplanner test assets <step>` lists what is already there, and the link is written exactly
as `test attach` printed it.

## When more than one person or process touches the same thing

Most tests assume one actor, and a screen that was loaded a moment ago. Both assumptions
break as soon as a product has several users, several tenants, a background job or a second
window open — and the bugs that live there are the expensive kind, because every
single-actor test passes while they ship.

**So ask it deliberately, on any system where more than one person or process touches the
same data: which of these tests needs a concurrent sibling?** If the person you are planning
with has not said whether concurrency matters, say what you would add and let them decide.
It is a recommendation, not a decision to make for them — and a plan that never asked is the
one that ships the bug.

Four shapes cover nearly all of it:

- **A stale screen, then a write.** B loaded the record before A changed it, and then B
  acts on what B can see. One person signs a document; the second still has it open as
  unsigned and presses Sign. What must happen — a refusal, a merge, a forced reload — is
  exactly what the test pins down.
- **Two writers at once.** A and B change the same field in the same second. First write
  wins, last write wins, or a conflict is shown: whichever this product does, say it.
- **Isolation.** What A can see, do, search, export or link never crosses into B's tenant,
  project or role — including after a role is revoked while B is still signed in.
- **Work happening behind the user.** An import, a scheduled job or another service changes
  a record while somebody is looking at it, or editing it.

A concurrent test is written like any other. What changes is that the preconditions name
**each actor and what their session has already loaded**, and every step names the actor it
belongs to:

```
## Preconditions
- Reviewers A and B, both signed in, in separate browsers.
- Document `D-101` in `Ready for signature`, open on both screens and loaded before the
  test begins — neither screen is reloaded until a step says so.

## Steps
1. A: sign `D-101` and confirm. A's screen reads `Signed`.
2. B: without reloading, press **Sign** on the same document.
3. B is refused — "signed by A a moment ago" — and B's screen refreshes to `Signed`.
4. Exactly one signature is recorded: check the document and its audit trail.
```

Two variations are worth naming where they apply. **The same user in two windows** is the
cheapest way to reproduce most of this, and belongs in the preconditions when it is the
intended reproduction. **Two agents or processes** running the same command against one
workspace is the same question without a screen — and the answer is usually that the second
is refused rather than that both proceed.

## The project's conventions win

This is the default, not a rule to paste anywhere. Where a project's topology, its standing
agent instruction, or the person you are planning with asks for tests in another shape,
write them that way. Never copy this document into a plan: every agent reads it here, and a
copy in a project's own prose is paid for again in every briefing.
