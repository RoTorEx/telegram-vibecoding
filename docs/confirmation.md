> Legacy reference: the production entrypoint is now notification-only. Do not
> activate executable Telegram intake or the confirmation server. See BUSINESS.md.

# Device confirmation operations

This feature authorizes individual Telegram requests before native execution.
It does not protect messages already in Telegram, compromise of the execution
host/user, a modified Telegram client, or an extracted biometric device secret.
Telegram's API provides a secret unlocked by local biometrics, not a signed
hardware assertion of a fresh scan. Support and OS fallback behavior require
acceptance on the actual owner's phone.

## Private HTTPS activation

The bot serves the Mini App in its existing process when enabled. Shared Compose
publishes only 127.0.0.1:8790. Keep Core's trusted Unix API private.

1. Choose an owned HTTPS hostname. Obtain a trusted certificate with DNS-01 to
   keep the application private, and resolve the hostname to the VPS WireGuard
   address on the phone. Private CA certificates need explicit phone/client trust
   and are not assumed to work in Telegram.
2. Through the gateway owner's reviewed onboarding workflow, proxy only the
   chosen app origin/path to 127.0.0.1:8790. Preserve Origin, allow JSON POST and
   the X-Telegram-Init-Data header, and disable request-body/authorization logging.
   Limit access to the owner's selected WireGuard peers, not the family subnet.
3. Configure the private bot.toml:

   ```toml
   confirmation_required = true
   confirmation_url = "https://YOUR_OWNED_HOST/confirm"
   confirmation_host = "0.0.0.0" # Inside the container; host publication is loopback only.
   confirmation_port = 8790
   ```

4. Deploy the committed bot using the shared make deploy-bot workflow. Enabling
   protection is fail closed: pending messages and mutating buttons stop until
   device confirmation succeeds. Existing native work continues.
5. Test the URL from the actual phone over WireGuard, then enroll it. Configure
   any Telegram/BotFather domain requirements only for this intended bot.

No server-only check proves working Face ID or Telegram WebView/VPN reachability.
Do not mark activation accepted until the phone checks below pass.

## Enrollment and revocation

Run these directly through your independent SSH connection to the VPS, from the
Remote Vibecoding root. Do not send the enrollment code through Telegram or ask
the agent to print it in a chat. These use the existing private bot database.

```sh
sudo docker compose --env-file .env exec -T bot telegram-vibecoding --auth-enroll
sudo docker compose --env-file .env exec -T bot telegram-vibecoding --auth-devices
sudo docker compose --env-file .env exec -T bot telegram-vibecoding --auth-revoke DEVICE_ID
```

Generate a code immediately before enrollment; it lasts ten minutes and issuing
another invalidates the previous code. Open /auth in the bot, allow biometric
access, paste the code into the Mini App, and store the key behind local biometrics.
If secure storage fails, revoke that device before trying again. A previously
saved but server-revoked key must be removed in Telegram's bot biometric settings
before enrollment. Deleting the chat or reinstalling Telegram is not recovery.

Losing a phone: revoke its device and VPN peer from independent administrative
access. Revocation cancels unused approvals; it cannot undo dispatched work.
Check active sessions and stop them administratively where needed. Enroll the
replacement phone using a new code. Never allow Telegram ID alone to recover keys.

Changing confirmation_required to false explicitly disables this protection;
it is an administrative recovery action, not a runtime error fallback. Rolling
back to a version predating these config fields will refuse unknown configuration,
so reconcile security configuration deliberately before any rollback.

## Phone acceptance

- Send text; verify no native request exists before confirmation, then confirm
  only that request on the enrolled phone and observe the intended session.
- Send an image album and a recording; review the exact previews, reject one,
  confirm another, and verify rejected media never reaches the native agent.
- Cancel the biometric prompt, disable biometrics and try an unenrolled device:
  all must leave requests unexecuted. Record whether the OS permits PIN fallback.
- Verify question choices, typed answers, Stop, settings, session creation and
  archive require confirmation; navigating menus requires none.
- Repeat a proof, let one expire, change the selected session, and restart the
  bot while requests await confirmation. No request may gain another's authority.
- Revoke a device with an outstanding approval and verify it cannot execute.
- Verify the HTTPS service is unreachable outside the VPN and from unselected
  family peers, on IPv4 and IPv6. Confirm other gateway applications still work.

Implementation tests cover these server boundaries with fake Telegram/native
transports; they do not establish actual phone biometric behavior.
