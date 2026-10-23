# Evolution Contract

Read this file when a user corrects or explains agent behavior, instructions are
unclear or conflicting, the same mistake repeats, a kernel improvement is being
considered, or `make vibe-pull` installs a new kernel version.

## The loop

The kernel and its children improve through a controlled feedback loop:

```text
observe -> repair locally -> propose with evidence -> review and generalize
        -> release -> pull and adopt -> observe again
```

The loop is self-healing, not self-authorizing. Agents preserve knowledge and
propose changes, but the kernel never silently rewrites itself or child product
truth.

## 1. Repair locally first

- Complete the current child task without waiting for a kernel decision.
- Preserve the user's explanation or correction in the correct local source of
  truth during the same task.
- Update code and protecting tests when behavior changed.
- Resolve local contradictions instead of adding another overlapping rule.

This prevents a meta-process from blocking the product work that produced the
evidence.

## 2. Decide whether feedback belongs in the kernel

A kernel proposal is justified when at least one is true:

- the same failure or correction appeared in multiple tasks or projects;
- the lesson applies broadly to agent workflow rather than product behavior;
- one occurrence exposed a high-impact safety, data-loss, security, or release
  risk;
- the user explicitly asks to make the behavior shared.

Keep product rules, domain terminology, architecture, UI behavior, and local
delivery details in the child. Do not generalize merely because a rule could be
worded generically.

## 3. Write a self-contained rule proposal

A substantive rule or proposal must make these clear, in prose or structured
fields:

- **Trigger:** when the rule applies;
- **Action:** what the agent must do;
- **Reason:** which failure it prevents and why the result is worse without it;
- **Evidence:** the correction, incident, repeated pattern, or test behind it;
- **Scope:** where it applies and important exceptions;
- **Verification:** how compliance or benefit can be checked;
- **Removal condition:** what evidence would justify narrowing or deleting it.

Do not paste raw conversations, secrets, private payloads, or unnecessary
project details. A future agent must understand the rule without access to the
originating session. Use plain language and keep one canonical home for each
idea. Do not restate a rule elsewhere: link or route to it. When new evidence
changes a rule, repair or replace the canonical text instead of adding a
near-duplicate.

### Submission algorithm

When feedback belongs in the kernel, or the user asks to update parent rules:

1. Repair local truth and complete the child change first; kernel feedback must
   not block it.
2. If `make vibe-propose` is unavailable, run `make vibe-pull`, review its diff,
   and retry the command.
3. Run exactly `make vibe-propose` and answer its prompts from known evidence;
   do not invent missing facts.
4. If writing to the parent needs filesystem approval, request approval to
   rerun that same stable command.
5. Never manually edit the parent's `FEEDBACK.md`, `core/*`, or other files from
   a child. If the command still cannot run, report the structured proposal and
   blocker in the final response without writing to the parent.
6. Continue child work after submission. A proposal changes no rule until the
   parent reviews it and releases a new version.

`make vibe-propose` is the only child-to-parent write path. It appends one
structured proposal to the configured parent's `FEEDBACK.md` and changes
nothing else.

## 4. Review in the parent

When changing kernel rules:

1. Read active `FEEDBACK.md` entries and the cited evidence.
2. Search current rules for duplicates, complements, contradictions, and a more
   general rule that already covers the case.
3. Prefer clarifying, merging, or deleting rules over adding another bullet.
4. Accept only the smallest reusable behavioral change.
5. Update kernel business rationale, tests, routing, changelog, and version as
   required.
6. Mark the feedback decision and retain its reasoning in Git history.

A proposal is evidence, not authority. The parent may accept, narrow, reject, or
remove a rule.

## 5. Release, pull, and adopt

- Shared rule changes are distributed only through a released kernel version.
- `make vibe-pull` copies every current `core/*.md`, the kernel `VERSION`, and
  managed routing; it removes obsolete managed runtime files.
- After a version change, read the changed kernel files and the adoption notes
  below before continuing work.
- Apply safe, relevant local instruction or documentation repairs in the same
  task. Do not invent product decisions or perform unrelated migrations.
- Commit the pulled kernel diff and any required local adoption as one explicit
  maintenance task.

## 6. Re-evaluate rules

Later incidents are evidence about existing rules. If a rule is ignored,
misread, duplicated, too broad, or produces worse outcomes, send that evidence
through the same loop. Useful rules may be clarified; unsupported rules should
be narrowed or removed.

Historical LLM sessions may be used during a dedicated audit to reconstruct
provenance and repeated failures. Normal child work must not depend on session
history access, and history must never be copied into instructions wholesale.

## Adoption notes

### 1.3.5

- Use `ROADMAP.md` for durable product direction and `TASK.md` for accepted,
  executable work. Keep both only when both horizons exist, remove empty queues,
  and migrate ambiguous `TODO.md` content according to its actual role.

### 1.3.4

- Define the smallest verifiable outcome before acting, respect documented and
  user-defined boundaries, and stop for approval before expanding beyond them.
- When consulting references or examples, begin with the closest relevant
  source and stop once the evidence supports a safe decision.

### 1.3.3

- Route bulky agent-created scratch, temporary checkouts, build outputs, and
  reusable caches to `${HOME}/construction_side/<project>/`. Keep that tree
  disposable; clean task-specific artifacts and never store the only copy of
  source truth or a user deliverable there.

### 1.3.2

- Clean up task-owned temporary files, directories, checkouts, build outputs,
  browser profiles, and processes before the final response unless they are
  still needed. Report every intentional retained artifact and its cleanup
  condition; never delete pre-existing or unowned data.

### 1.3.1

- Before the first tag pushed through a new or materially changed automated
  publishing workflow, apply the practical preflight and post-push verification
  added to `RELEASE.md`. No publishing system or unsupported target is required.

### 1.2.0

- Run `make vibe-pull` once. It adds the managed `vibe-propose` Make target
  while preserving every project-owned byte outside kernel markers.
- Submit reusable feedback only through `make vibe-propose`; do not manually
  edit parent files from a child.

### 1.1.2

- Pull the clearer one-rule-one-home writing contract and the initial-commit
  convention.
- Existing history is not rewritten. Apply `Initial commit` only to repositories
  that do not yet have a first commit.
- Local Makefiles should expose only real capabilities; projects without a real
  release process omit release targets.
- Remove legacy kernel-managed `.githooks` and its local `core.hooksPath` during
  adoption; Stage 1.x no longer distributes or requires Git hooks.

### 1.1.1

- No project migration is required.
- Run `make vibe-pull` to give child agents the stable interactive release
  invocation contract.
- Existing project release tooling remains valid when `make release` prompts
  for the exact version; agents must no longer encode that version in the shell
  command.

### 1.1.0

- Existing children should run `make vibe-pull` to receive this contract and the
  dynamic runtime sync behavior.
- Apply the local knowledge-capture rule going forward; no bulk rewrite of old
  project documentation is required.
- When an existing rule is next changed, make its trigger and rationale
  self-contained using this contract.
