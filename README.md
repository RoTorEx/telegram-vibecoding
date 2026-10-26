# Telegram Vibecoding

The private Telegram interface of Remote Vibecoding.

Open @GardenSandbox_bot and send /menu. Choose Location, a numbered host
directory, then a session. Sending text, images or voice from the location's
session list starts a new session there. Session controls put Config, Details
and History on the first row, an emergency Stop on its own full-width row only
while work is active, and Back/Deck last. Config contains model, reasoning and
Plan settings. History reads ordered pages continuously and offers separate
iteration jumps between execution iterations. Each iteration starts at the initial
user request and includes steering additions, progress, published reasoning,
questions and answers through completion. Consecutive roles share pages when
they fit, so the conversation reads from top to bottom. Image pages show attached media
directly; text pages remove it. Main Deck contains account Limits and reset
times. Completion notices show elapsed work time and Open session; the active
panel moves below notices and keeps its captured session context. Long answers
arrive in full as consecutive messages above the controls. Their parts remain in
Telegram after follow-ups; History still contains the complete conversation.
Opening Journal publishes only the current answer. Older partial delivery never
appears after a newer result; read previous iterations through History.

Text and images go directly to Vibecoding Core.

Optional device confirmation keeps each executable request pending until an
independently enrolled phone authorizes it through a biometric Mini App. See
[activation, enrollment and recovery](docs/confirmation.md). The patch alone does
not enable protection: trusted private HTTPS and phone acceptance are required.

Run make install and make check. Integration checks require the sibling
vibecoding-core checkout; the deployed bot has no Core package dependency.
Common Compose operations are run from the parent Remote Vibecoding workspace.

Each component has independent semantic versions, changelog and annotated Git
tags. The canonical version is its own src package __init__.py; Hatch derives
package metadata from it. uv.lock locks dependencies and records the root
package as dynamic; the installed metadata and wheel carry the concrete version.
Run make release interactively and enter MAJOR.MINOR.PATCH at the prompt; this
checks, updates metadata/changelog and creates a local release commit/tag.
Then make release-push atomically pushes only this repository's main and release
tag and verifies the remote references. Neither command deploys or releases the
sibling. Common deployment continues to select each image revision separately.

Both projects use Vibecoding Kernel 1.3.5. Run make vibe-pull to refresh the local
committed rules; make vibe-kernel-set configures the machine-local kernel path.

Local message and media copies expire seven days after saving, checked every
15 minutes. Pending/active work is retained until it resolves. The configured
state directory owns bot.db, engine.db and uploads; native Codex history and
Telegram cloud messages are outside this cleanup.
