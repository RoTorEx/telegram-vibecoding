# Telegram Vibecoding

The private Telegram interface of Remote Vibecoding.

Open @GardenSandbox_bot and send /menu. Choose Location, a numbered host
directory, then a session. Sending text, images or voice from the location's
session list starts a new session there. Model/reasoning/Plan controls live in
the chat; Details groups status, location, timeline, storage, rename and close.
You/Codex/Updates separate original input, agent output and public progress.
Previous/Next browse history, Now returns to current output, and Page appears
only for long text. The compact title/model/status header stays live while browsing history. Main Deck
contains account Limits and reset times. Finished sessions send short standalone
notifications without acknowledging unread results. Images are delivered as
original documents and remain downloadable through the session's Images view. Back/Deck are the final row.
Text and images go directly to Vibecoding Core.

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
