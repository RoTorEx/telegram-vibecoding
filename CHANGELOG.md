# Changelog

## [Unreleased]

## [0.1.23] - 2026-10-26

- Finish started long-answer deliveries across session changes, menu navigation and restarts; restore previously cancelled undelivered parts within the seven-day retention window.
- Put Config, Details and History together on the first session row, with a full-width Stop row only while work is active.

## [0.1.22] - 2026-10-26

- Add optional per-request Telegram Mini App biometric confirmation with independent one-use SSH enrollment, device revocation, signed immutable requests, media previews, durable pending input and protection for session controls and question answers. Activation requires private trusted HTTPS and phone enrollment.

## [0.1.21] - 2026-10-25

- Display and answer asynchronous native questions using normal choice/free-text controls and Waiting state, including while the agent continues independent work.

## [0.1.20] - 2026-10-25

- Deliver complete long answers as consecutive persistent messages above the session controls, with durable per-part retries, session-scoped replay, and seven-day local retention.

## [0.1.19] - 2026-10-25

- Suppress completion notifications for the session currently open in chat or history, preserving background notices, durable deduplication and normal panel updates.

## [0.1.18] - 2026-10-25

- Show reasoning effort beside the model, rename history chapters to iterations, and quote published reasoning while preserving full conversation order.
- Return from history to the session dialog after accepted input, including follow-ups and question answers; preserve iteration boundaries until actual completion or confirmed interruption.

## [0.1.17] - 2026-10-25

- Fix missing agent replies in history by grouping complete execution iterations, including steering additions, questions and published reasoning, instead of splitting at every user input.
- Pack consecutive role blocks into readable pages, preserve complete published text, and map existing history cursors to the corrected chapters.

## [0.1.16] - 2026-10-24

- Replace role filters and the image gallery button with a dedicated chapter/page history reader, including inline request-scoped images and continuous page navigation.
- Restore Config beside Details and keep Chat history/Stop and Back/Deck as the remaining main session rows.
- Include elapsed work time and Open session in completion notices; keep the active panel below standalone notifications and file deliveries.

## [0.1.15] - 2026-10-24

- Simplify chat to title, model/status and agent output; use You/Codex/Updates and contextual Previous/Next/Now and Page controls. Clear stale format notices after accepted input.
- Expire local transport message/media copies after seven days, preserving pending input, active files and durable read/deduplication cursors.

## [0.1.14] - 2026-10-24

- Route registered image events through polling so originals reach Telegram automatically.
- Retry startup panel flood waits in the same process without repeating accepted readiness notices.

## [0.1.13] - 2026-10-24

- Group session details and journal entries, move model/effort/Plan controls into chat, and separate Request, Answer and Progress views with an always-live activity button.
- Show real account quota windows and Warsaw reset times in Main Deck and Limits.
- Start a captured new session for voice/text/images sent from a location's session list; preserve creation/input identities across fast input and retries.
- Send short durable completion notifications without marking results read.
- Deliver registered image originals and retain downloads in request-scoped session history galleries.

## [0.1.12] - 2026-10-24

- Send persistent owner startup notifications with bot/Core versions, host and Warsaw time, independently of the replaceable session panel.

## [0.1.11] - 2026-10-24

- Make Journal a full session switcher with execution, question, queue and durable read statuses; sort every session list by latest interaction.
- Show eight sessions per page with two rows of four numbers; add New/Edit controls and explicit archival with retained history/files.
- Restore the home emoji, remove selected-location details from Main Deck, and add Terminal beside Settings for service/version information.
- Separate exchange navigation from text-page navigation, repeat author/type labels across long queries and replies, and quote user input.
- Put Config/Details first and Pause beside exchange navigation; display approximate relative times in italic parentheses.

## [0.1.10] - 2026-10-24

- Fix incoming button/reply serialization of SDK link-preview defaults that could block all commands behind one update.
- Recover expired callback acknowledgements and detect stalled polling in health checks.

## [0.1.9] - 2026-10-24

- Add Main Deck unread-result counts and a paginated Journal with durable explicit-view acknowledgements.
- Notify the owner on bot restart while preserving the selected session and single-panel navigation.

## [0.1.8] - 2026-10-24

- Hide untouched empty session drafts from location lists while preserving their records and history.
- Use 👽 for Main Deck and Deck navigation, and show location names in bold with plain paths in parentheses on one line.

## [0.1.7] - 2026-10-24

- Render agent Markdown as safe Telegram formatting with readable table rows and balanced formatting across history pages; keep original messages intact.

## [0.1.6] - 2026-10-23

- Keep Stop available during voice preprocessing and refresh the transcript as soon as it is stored.

## [0.1.5] - 2026-10-23

- Accept Telegram voice recordings, preserve their captured session and show local transcripts in user history; video remains unsupported.

## [0.1.4] - 2026-10-23

- Show compact last-response ages and active-work markers in ten-session pages,
  with paired left/right controls and periodic visible-list refreshes.

- Remove manual location entry and archive browsing/reopening from the interface.
  Keep Config inside an open session and use Back-left/Deck-right footers on
  every screen. Recover an already-open retired archive view safely.

- Use Telegram's default Settings button styling while retaining its full-width
  first row.

## [0.1.3] - 2026-10-23

- Apply panel positioning to every message/command, including empty Stop and
  unknown commands, and refresh promptly after agent input is accepted.
- Animate active work with elapsed time and reasoning effort. Show public
  summaries as separated history blocks while hiding live code and tool output;
  preserve final answers and original user input.

## [0.1.2] - 2026-10-23

- Keep the active panel below new owner messages: Start/Menu, text and media
  relocate it to the chat tail while buttons and streaming edit it in place.
- Repair stranded panels from the durable inbox at startup. Retire old bot
  panels only after replacement succeeds, retry cleanup without duplicate sends
  and recover expired controls directly into Main Deck.

## [0.1.1] - 2026-10-23

- Add independent Kernel-compliant interactive release and atomic tag publishing,
  with one canonical package version and matching CLI/build metadata.
- Show the independently running Telegram and Core versions in Settings.

- Extract the working Telegram interface into its own private repository and
  runtime package, preserving UI, session routing and durable state.
- Add a separate image/container and per-boot readiness for one Remote Vibecoding
  Compose workspace with independently managed Core.
