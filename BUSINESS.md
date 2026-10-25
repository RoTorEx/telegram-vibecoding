# Telegram Vibecoding

## Purpose and actors

Aleksey uses this private Telegram interface to work with native host agents
through Vibecoding Core. Only the configured numeric owner in their private
chat may send input or use callbacks. No extra LLM or rewritten prompts.

## Interaction contract

Main Deck and its navigation button use 🏠. Main Deck has Settings and Terminal
side by side, followed by Location and Journal. Its text shows session counts,
without a selected location or path. Terminal reports bot/Core versions, protocol,
host, Core revision/health, native process, intake, queued inputs and session/
question/unread counts. Model, reasoning and Plan controls live in session Config; Settings explains
that location. Account Limits is available from Main Deck and shows native quota
windows, remaining percentages and reset timestamps with Warsaw's actual zone.
Unknown/unsupported data stays unavailable; reset credits are never consumed.
Use Telegram's default button styling without a primary color accent.
Every screen ends with Back on the left and Deck on the right in one row. Home is the default first
location. Numbered 1–8 controls page through locations and directory-scoped
sessions. Location choices show the bold project name and its plain path in parentheses on one line.
Selecting a location does not start an agent. Sending text, supported images or
voice from that location's session list creates a session in its captured path.
Fast messages from the same list visit share a durable creation intent. Capture
the path/intent before navigation or downloads; retrying session creation and
input must reuse their identities. Main Deck/Settings input never starts work. Untouched, idle New session drafts
without native threads or captured input are hidden from session lists; the New
session button remains available. Draft records and history are preserved. The ➕ New action appears only within a location, beside ✏️ Edit.
Edit is also available in Journal; its scope is the location or all projects,
respectively. It lists drafts too, and opens an explicit Archive action stating
that active work will stop. Archiving hides the session from active lists while
retaining history and project files. There is no permanent-delete action. Locations are existing registered directories; do not expose
a manual Other location input action in this menu.

The main session screen contains its title, a compact model/status line with
reasoning effort in parentheses next to the model (for example,
GPT-6.1-Sol (medium) · Working), and current agent output. It has exactly three normal control rows: Config and
Details; Chat history and emergency Stop; Back and Deck. Config contains model,
reasoning and Plan controls. Do not put these controls, role tabs, Images or
history pagination on the main screen. Long current answers are delivered in full as consecutive standalone messages;
the controls remain in a separate compact panel below them. Native pending questions add
only their required answer controls. Stop retains native identity and history.

Chat history is a book reader of the entire retained conversation. An iteration
spans the initial user request through the agent's terminal completion, including an interruption confirmed by the agent after Stop.
Pressing Stop alone never ends an iteration. Steering additions, question
answers, progress, published reasoning, questions and final responses stay in chronological order inside that iteration.
A new request after completion begins a fresh page/iteration. Never infer iteration
boundaries from each user event: that hides replies after steering additions.
The reader follows the retained Core event feed incrementally, with a full
refresh every minute to reflect seven-day expiry. Existing steering anchors
resolve to their containing iteration; reset legacy page offsets once.

Pack consecutive role blocks onto a page, starting with the user's original
request and continuing with agent output below it when space permits. A fitting
user message stays whole; an oversized message continues with a repeated You
label. Text pages reserve 3500 visible UTF-16 units including role headings,
leaving room for title/status and counters within Telegram's 4096-unit limit.
Keep all published reasoning text, including code, in history. Raw tool output
and unpublished reasoning are not conversation events. Repeat author/type labels
on continuation pages. Render published reasoning in blockquotes, with its
Reasoning author label outside the quote; preserve its text and formatting
across page boundaries.

Accepted text, images or voice sent while browsing history return the selected
session to its main dialog controls, for both steering and new iterations.
Question answers follow the same rule. Keep the captured input target and avoid
replacing a different session/menu selected while delivery was pending.
Automatic return does not acknowledge a completion.

Page arrows read continuously across iteration boundaries: forward enters the next
user page; backward enters the preceding iteration's last page. Iteration arrows
always jump to the user page at the start of the adjacent iteration. Opening Chat
history starts at the current iteration's first user page. Back restores the live
session. Browsing uses a captured anchor/page cursor, so new output does not jump
the reader to another iteration. Current activity/elapsed time remains in the
header. There are no You/Codex/Updates filters or separate image gallery controls.

Images are actual page media, scoped to their original request. User uploads
follow their matching user block, and registered output images occupy their
corresponding pages. Pack adjacent text into image captions up to 800 visible
UTF-16 units including role headings, reserving room for metadata within
Telegram's 1024-unit caption limit; continue long text on text pages. Photos use
the 10 MB photo ceiling; larger supported originals (up to the existing 20 MB transport ceiling)
use documents, and GIF uses animation. Returning to a text page removes media
from the working panel. Preserve downloadable originals and attachment anchors.
Only explicitly viewing the latest iteration's final page, or a complete current
answer, acknowledges a completion. Browsing user/older/partial pages, Config,
Details and background refreshes never mark new outcomes read.

Details uses separate bold identity/status, Location, Timeline and Storage blocks.
It contains title, host, directory, location, creation/request/response/completion
times and free disk space. Rename and Close live here. Times use
Europe/Warsaw and their date-specific UTC offset. Navigation leaves work running;
Stop interrupts it; Close ends the session without deleting project files.
The bot has no archive browser or reopen action; closed history remains stored.

## Transport and state

Text and supported images pass unchanged to Core. New messages steer active
work. The 20 MB Telegram cloud download ceiling is enforced. Agent response parts
are at most 3200 UTF-16 units, leaving room for the header and notices below the
4096-unit API limit. Albums use a one-second quiet window and retain their first
captured target. Outgoing changes are throttled to at least one second, with
Telegram retry_after taking precedence.

The frontend owns bot.db: captured input, UI state, offsets and output refresh
requests. Input targets are captured before downloads/navigation. Button navigation and streaming edit the current panel. A new owner message
moves the panel below that input by sending the replacement first and retiring
the previous bot panel. Telegram edits cannot change message order. Preserve
owner messages in Telegram and the locally retained seven-day history. Track the latest input and
unfinished retirement durably, including across upgrades. A failed replacement
send preserves the old panel; failed cleanup never repeats the successful send.
Startup refreshes the saved view and repairs a panel stranded above newer input. Native questions and free-text
answers remain associated with their originating session. Errors retain
navigation exits. An unavailable panel can be replaced without replaying input.


## Complete long-answer delivery

When a current answer exceeds the compact preview, publish its complete native
final messages as ordered standalone Telegram messages, splitting rendered HTML
at 3500 visible UTF-16 units and repeating the session/part heading. This leaves
room below the 4096-unit Telegram limit. Preserve every text character and valid
formatting; do not summarize or require the owner to use history for the rest.
Short answers retain the existing single-panel presentation. Published answer
messages have no controls and are never retired as UI panels. After full delivery,
remove the duplicate compact preview and keep the normal three control rows in
the working panel below the answer. Keep errors and pending questions visible.

Queue and acknowledge each part durably by view visit, event ID and part number.
Refreshes and process restarts resume pending parts without repeating accepted
ones. An explicit session selection replays its current long answer at the chat
tail; returning from Config/history retains the same visit. Navigating away pauses
delivery; opening a new visit cancels obsolete pending copies, preserving source
history and already delivered messages. Follow-ups in the same session keep
accepted answer parts and may continue the current iteration normally.

Only the selected main session dialog receives full-answer messages. Background
sessions retain short completion notices and publish full answers when opened;
history remains a role-aware book. Answer parts are silent and disable previews.
Keep the panel below each accepted part, including partial-delivery failure.
Sending an answer automatically does not acknowledge a result. An explicit open
captures its completion receipt and acknowledges it only after all requested
parts reach Telegram; a newer completion must remain unread. Local queued/sent
answer copies expire after seven days from the original event, like other local
message content. Do not backfill expired answers or change native identities.

## Deployment boundary

This is one of two containers in the Remote Vibecoding Compose project.
Production code talks only to the versioned Core API, never imports Core code.
Integration tests use the sibling Core checkout; runtime packaging does not.
Restarting/updating this container must not restart Core or native agent work.
The accepted bot is @GardenSandbox_bot, displayed as Telegram Vibecoding.
Voice recordings are downloaded privately and queued to Core for local speech
recognition. Display the exact transcript as user input. One recording is limited
to five minutes and 20 MB; stable downloads and captured targets survive retries.
Video is out of scope.
Additional hosts remain deferred. No subagents.

## Independent versioning

This component owns its semantic version, changelog, release commit and annotated
vMAJOR.MINOR.PATCH tag. The sibling version and deployment revision do not change
when this repository is released. API protocol compatibility is separate from
product versions. Follow the local Kernel release contract through make release
and make release-push. Source package version, built metadata, CLI and runtime
version reports must agree.

## Active work display

The one-panel positioning rule applies to every owner message and command,
including plain menu input, attachments, input steps and Stop without a session.
Unknown bot commands stay in the interface instead of reaching an agent; absolute
directory input remains valid. Accepted agent input refreshes the panel promptly.

While a turn is active, animate a compact working indicator with elapsed time
and the configured reasoning effort. Never invent remaining time. Show only
public native summaries and code-free progress prose, separated chronologically
above the finished answer. Hide command/tool output, diffs and code blocks from
progress. Do not display raw reasoning. Final answers and original user prompts
remain intact. Completed summaries stay browsable in the paginated history.

Session lists show at most eight entries per page, with four numbered buttons
per row (two full rows for eight sessions). This phone layout bounds menu length
and keeps controls usable; locations use the same picker. Paired page arrows
clamp at the first/last page. Every session list, including Journal and Edit,
sorts by Core last_interaction descending with stable ID tie-breaking. Core
owns interaction semantics; explicit viewing does not reorder sessions.

Lists distinguish Connecting, Transcribing, Working/live activity, queued input,
questions waiting for the owner, finished unread results waiting for the owner,
Read/Idle, Failed, Interrupted and Uncertain. Unknown statuses remain visible.
Pending questions take precedence over active-turn markers, including native
user-input and MCP elicitation contracts. Result read state uses the durable
completion cursor independently of execution state. Relative ages use italic
parenthesized approximate notation, e.g. (~1h); elapsed active time follows the
same notation. Absolute detail/restart timestamps retain their Warsaw zone.

## Agent Markdown display

Parse native answer Markdown for display using a real parser, then emit only
Telegram-supported HTML formatting. Preserve original events and user input.
Bold, italic, strikethrough, headings, links, lists, quotes and code are readable;
raw HTML is literal text. Tables become readable rows for narrow phone screens,
preserving headers and cell contents. Do not rewrite the agent prompt to enforce
an output format. The live compact preview keeps its existing code filtering; history preserves
the full published progress and reasoning summaries.

The compact answer preview uses its existing 3200-unit budget. History packs
role blocks using the iteration budgets above. Mixed/export views use bold author/type labels: 👤 You, 🤖 Codex · Answer,
💬 Codex · Progress, 🧠 Codex · Reasoning, or a labeled question/system outcome.
Quote the original user input; use a visible divider only between distinct
blocks sharing a page. Reopen formatting on every page, including quotes/code.
Role labels and counters are display metadata; retain all original text and
native events unchanged. Long user input and long replies are both browsable. Escape session names, paths, errors, typed
prompts and transcripts. All menus retain their normal buttons; formatting never
changes callbacks, session identity or original history. Disable link previews
to keep the single panel compact. Older answers are formatted when reopened.

## Session journal, read state and restart notices

Main Deck shows running/waiting counts and an always-visible Journal button with
the number of non-closed sessions having a finished outcome not explicitly
viewed by the owner. Journal is the general session switcher across locations,
including active, question-waiting, finished, read and unread sessions. Opening a
result changes its read label but does not remove it from Journal. Busy sessions
are excluded only from the unread finished-result count until they finish.
Failures and interruptions can also require attention.

An outcome becomes viewed only after an owner navigation opens its latest chat
page, or history navigation reaches that page, and Telegram successfully accepts the
panel. Opening Journal/Config/Details, browsing older history and background
updates never acknowledge it. Telegram supplies no user read receipts to this
bot. Per-session completion cursors persist in bot.db, advance monotonically and
acknowledge only the displayed event; a later completion stays unread. On first
upgrade retained unacknowledged results are visible rather than silently read.

Every process boot sends the owner one standalone online notification with
bot/Core versions, host and Warsaw time. Request Telegram notification delivery
explicitly (disable_notification=False); the owner's chat/device settings still
control sound and push delivery. Keep this message outside the replaceable UI
panel, with no navigation buttons. Later input, streaming and panel cleanup must
not edit or delete it. Persist the accepted message ID/text and boot cursor
before refreshing the UI, so panel failures and retries do not resend a known
successful notification. A failed send leaves the cursor pending. A new boot
gets a new notification; no historical notification backfill is sent.

Refresh the selected view after notification delivery and retain the single
working panel, owner messages, explicit-view cursors and all native execution.
Restarting the interface does not mark results viewed. Tests cover retained
notifications after navigation, repeated startup, failed sends and panel failure
after a successful notification.

## Telegram intake and liveness

Persist only fields actually received in incoming SDK updates, recursively using
exclude_unset. Missing LinkPreviewOptions fields contain SDK Default sentinels,
which are not Telegram JSON and must never enter durable input. Button callbacks
and replies to bot panels carry these options. Intake preserves supplied media,
aliases, session targets and unknown JSON fields; it never drops an update to
escape a serialization failure. An expired callback acknowledgement returns to
usable navigation and finishes that control, without blocking later commands.

Readiness requires the current boot/PID and a successful polling/intake heartbeat
no older than 120 seconds. Long polling is 25 seconds with a 35-second request
deadline, so the bound tolerates several transient retries while exposing a
stalled consumer. Advance the heartbeat after durable acceptance/control handling,
not before the potentially failing serialization. A live process alone is not a
healthy interactive bot. Tests cover typed callbacks/replies with preview options,
subsequent commands, expired acknowledgements and stale polling health.

## Completion notices and image delivery

A background terminal event sends a short standalone owner notification containing location,
session name and outcome (finished, failed, interrupted or the native terminal
status). A durable event-keyed delivery record prevents resending a known success
on restart; failed sends remain pending. Suppress completion notices when the
owner has that session open in its chat or history screen. Persist suppression
at event capture and recheck immediately before sending, including after retries
and throttling; leaving the session later must not resurrect a suppressed notice.
A remembered selection on Main Deck, menus, or a different open session does not
suppress background notices. Image-original delivery remains independent.
Suppression does not acknowledge the result or skip normal panel updates.
Notifications never mark a result read
or replace the working panel. Ignore historical events predating the feature's
first activation. Session lists retain their explicit-view unread count.

The Core attachment contract copies explicitly selected PNG/JPEG/WebP files into
private uploads, scoped to session and user-request anchor. Original delivery
remains durable; browsing shows each image directly in its matching history
page. There is no persistent Images button or separate gallery in session chat.
Navigation retires only the working panel/media, never original owner messages,
standalone file deliveries or completion notices. Producers register selected
images through the Core API; the frontend does not import Core code.

Completion notices show location, session, outcome and elapsed work time in
italic approximate parentheses. Derive elapsed time from the first retained user
input after that session's previous terminal event to this terminal event;
steering does not reset it. This includes preprocessing and waiting for input.
Missing historical evidence is explicitly unavailable, never session age or a
fabricated duration. Every notice has one Open session button targeting its
captured session, independent of the active project/menu. Merely delivering it
never marks results read.

Persist the highest accepted standalone notice/file message ID as a panel floor.
After delivery, refresh the active panel below that floor; subsequent navigation
and interactions keep the panel at the chat tail. Telegram edits cannot reorder
messages: send the replacement first, persist it, then retire the old working
panel. Keep notices and read cursors intact across UI retries and restarts.

## Seven-day local retention

The owner requested bounded VPS storage: local message content, transcripts,
received media and registered image originals expire 604800 seconds (seven
24-hour days) after saving, independent of reads. Both processes check every
900 seconds (15 minutes); cleanup also runs at bot startup. All bot-owned files
live under the configured data_dir/uploads, with message records in bot.db and
Core's engine.db in that same state root. Do not add permanent cleanup services.
Core owns event/request content and registered attachment files; the bot owns
its input/output copies and intake/orphan files. Migrate legacy output timestamps
from Core events rather than restarting their seven-day clock. Missing expired
anchors are safe and IDs/cursors never move backwards.

Keep pending input and active/question-waiting session files until work resolves,
then expire overdue content at the next check. Scrub completed inbox payloads,
remove expired output/notices, compact SQLite and retain only small identity/read
cursors needed to prevent duplicate execution and unread-state regressions.
This is local bot storage retention: Telegram cloud messages, native Codex
context/history, repositories, credentials, speech model cache and existing
backup retention have their own owners. Do not delete them through this janitor.
Tests protect the exact cutoff, reads not extending lifetime, pending/active
work, legacy timestamps, outside paths/symlinks and original input preservation
inside the retention window.
