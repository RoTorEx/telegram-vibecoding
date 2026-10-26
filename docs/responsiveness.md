# Asynchronous Telegram interaction

The owner requested responsive phone controls after observing 10–15-second button
waits. This change addresses frontend waiting, not native inference speed. It adds
no execution approvals, changes no Core API and does not enable device confirmation.

## Before

The 26 October 2026 audit correlated 26 callbacks on bot 0.1.24 with durable intake
and handler logs: median capture-to-handler completion 6,181 ms, maximum 15,277 ms.
The slowest example waited 5,941 ms before its handler and 9,336 ms inside it.
These exclude the phone-to-server interval. Queued writes used a 3.1-second
interval while rendering held UI state; polling awaited control rendering.

Common Core reads measured approximately 0.7–15 ms; Details, which inspects the
host directory, measured approximately 610 ms. Eight authenticated read-only
Telegram requests with reused aiohttp connections in the bot container had a
31.1 ms median. Separate cold-connection urllib checks had unexplained ~8-second
outliers: intermittent transport delay remains possible. VPS resources were not
saturated during the short sample. These are observations, not universal latency
guarantees.

## Boundaries

1. Polling stores raw authorized updates with status `received` before advancing
   the monotonic offset. It performs no UI rendering or media transfer.
2. Callback acknowledgements run independently with a two-second request timeout.
   Acknowledgement means the button was received, not that its action succeeded.
3. Ordered navigation captures targets only after preceding controls. It changes
   dialog state and queues a snapshot; network delivery runs elsewhere.
4. The panel publisher waits outside UI state, chooses the latest snapshot,
   sends/edits the panel, and then saves accepted message/media IDs. Identical
   content does not consume another Telegram write. A newer snapshot may supersede
   one already in flight; it is published next without acknowledging the old
   snapshot's explicit-view receipt.
5. At most four input targets run concurrently, ordered within each target.
   Authorized Stop/Archive cancels local transfer/queue work before native Stop.
6. Durable answers, notices and cleanup retain their existing retry/no-replay
   behavior. All chat writes share the 1.05-second budget and persisted flood wait.
   Callback acknowledgements and Core requests do not consume that write budget.

Core is a trusted private Unix API, unchanged by this patch. Existing per-request
biometric authorization still runs before mutations, including local cancellation.
Captured text/media, native identities, long-answer ordering, seven-day retention
and independent bot updates remain supported.

## Verification and limits

`tests/test_async_transport.py` exercises the production queue boundary with
controlled stalled HTTP, the production pacing default, real dialog dispatch and
the test Core API. It checks that input capture, acknowledgement and navigation
complete within 200 ms while panel HTTP remains deliberately blocked; it also
checks target ordering, coalescing, no-op output, failed-delivery/read state,
flood waits, independent sessions and cancellation. This bound is a regression
threshold under controlled transport, not a measured iPhone response time.

Run `make check`. Existing formatting/state tests inline the publisher through
an explicit fixture; the async transport tests bypass that fixture. Deployment
must verify the installed revision, successful startup/panel publication, polling
heartbeat and unchanged Core container/native identity. New logs record only
update ID and capture-to-navigation completion time, without message content.

Actual Telegram edits can still wait for the shared rate budget, server flood
wait, network connectivity, or a slow Core/host operation. Background previews
are expendable; captured input, final answers and explicit actions are not.

Telegram guidance: https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this
