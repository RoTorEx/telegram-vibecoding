# Telegram Vibecoding

The private Telegram interface of Remote Vibecoding.

Open @GardenSandbox_bot and send /menu. Choose Location, a numbered host
directory, then a session. Config changes native model/reasoning/Plan settings;
Details contains metadata, rename and archive. Deck/Back are the final row.
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
