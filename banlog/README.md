# BanLog

When a member is banned with message deletion, Discord purges their messages without sending any delete event, so no
logging cog can see what was removed. BanLog keeps its own rolling copy of Unicornia's messages and, on every ban,
copies the banned member's messages into a permanent ban record. Staff read the records on `staff.unicornia.net` (the
Dashboard cog).

- Every non-bot, non-webhook message posted in Unicornia is stored with its content, latest edit, attachment filenames,
  and deletion time. Attachment files are not downloaded.
- Stored messages are pruned hourly once they are more than 7 days old, the longest window a ban can purge.
- Bans from any source (`[p]ban`, Honeypot, Discord's menus, other bots) are read from the audit log. The record holds
  the user, their username, the moderator, the reason, the ban time, and their messages from the week before the ban.
  For `[p]ban`, the real moderator is read from the start of the audit reason.
- An unban sets the unban time on the user's latest open record. Records are never pruned.

Messages and bans that happen while the bot is offline are not captured.

There are no commands. Loading the cog starts capture immediately.

## Hardcoded values

| Setting | Value |
| --- | ---: |
| Guild | `684360255798509578` |
| Message retention | 7 days |
| Write batch | every 5 seconds or 200 changes |

## Required bot permissions

- `View Audit Log` (`view_audit_log`) in Unicornia. Without it no ban is recorded; the cog logs a warning at load, hourly,
  and when the bot's roles change.
- The message content intent, which Red already needs for prefix commands.

## Storage and data deletion

Data lives in `banlog.sqlite3` in the cog's data folder, readable only by the bot's Unix user.

| Requester | Stored messages | Their ban records | Bans they issued |
| --- | --- | --- | --- |
| `user` | deleted | kept | kept |
| `user_strict`, `owner`, `discord_deleted_user` | deleted | deleted | moderator becomes placeholder `0xDE1` |

Delete the SQLite file to discard everything BanLog has captured.
