# Data governance

This document is the per-cog annex to the bot's [Privacy Policy](PRIVACY.md), which covers the whole instance including community cogs. This repository treats Discord IDs as personal identifiers even when no username is stored. Each cog's `info.json` describes its persistent and externally processed data. Cogs with user-linked persistent records implement Red's `red_delete_data_for_user` hook.

## Retention and deletion

| Cog | Persistent or externally processed data | Deletion behavior |
| --- | --- | --- |
| AntiNuke | Trusted user IDs; quarantine role snapshots, reasons, and timestamps | Removes trust and quarantine entries |
| AutoMod | Action log of the newest 250 automod actions (time, member ID and name, channel ID, matched rules, actions taken); no message text. Per-member message counts for spam rules in memory only | Every request removes the user's log entries and in-memory counts; entries also drop out once 250 newer ones exist |
| BanLog | 7-day copy of every non-bot Unicornia message (author/channel IDs, content, latest edit, attachment filenames, deletion time); permanent ban records with user ID, username, moderator ID, reason, ban/unban times, and the banned user's messages from the week before the ban | Stored messages pruned hourly after 7 days. `user` requests remove stored messages and keep ban records as moderation records; `user_strict`, `owner`, and `discord_deleted_user` also remove the user's ban records and replace them as moderator with placeholder `0xDE1` |
| Confess | Confession text posted to Discord; author ID/content audit messages sent to bot owners | No local per-user record; Discord retention and deletion tools apply |
| ContestCog | Saved contest payouts: for each contest, the channel ID and the paid places' user ID, name, votes, and reward amount | Replaces the user's places with a "Deleted user" placeholder; the place and amount stay so other winners' records remain consistent |
| CustomCommand | User limits, command ownership, triggers, and responses | Removes limits and commands owned by the user |
| CustomEmoji | User limits and emoji ownership | Removes limits and ownership records |
| CustomRoleColor | User-to-role management assignments | Removes the assignment |
| DisboardReminder | Per-member Disboard bump counts saved by older versions of the original cog; no new records | Removes the user's counts from every guild |
| Dashboard | Staff login sessions (Discord user ID, CSRF token, expiry) in memory only; page traffic passes through Cloudflare | Nothing persistent; sessions end after 12 hours, on logout, or on unload/restart |
| Honeypot | Guild-scoped user IDs, prior role IDs, and quarantine timestamps | Removes the user's quarantine records from every guild |
| Mjolnir | Per-user count of successful hammer lifts | Removes the user's count |
| Moderation | Guild/member IDs, role IDs removed by a mute, and the mute end time | Removes the user's mute records from every guild |
| NitroAward | Guild/member boost timestamps and legacy boost markers | Clears member and legacy records |
| Patron | Patreon/Buy Me a Coffee names, emails, pledge amounts, payment progress, and the Discord IDs they are linked to | Removes the user's links and payment records; Unicornia financial entries follow its policy |
| Profile | Questionnaire answers, picture URLs, message IDs, and timestamps | Clears member-scoped and legacy user-scoped records |
| Roleplay | Per-user settings: public, servant, and selective flags, and the user IDs in each member's owner, allowed, and blocked lists | Removes the user's settings and their ID from every other member's lists |
| RulesAccept | Acceptance member ID and submitted text posted to a Discord log channel | No local per-user record; Discord log-retention policy applies |
| Suggest | Author IDs, suggestion text, message IDs, status, and review reason | Removes suggestions authored by the user |
| Tickets | Owner IDs, answers, channel/message metadata, avatar URL, timestamps, and lifecycle state | Removes ticket tracking and blacklist entries; Discord messages/channels remain subject to server moderation policy |
| UnicornAI | User opt-out preference | Clears the preference; channel history is processed transiently by the configured provider |
| Unicornia | XP, balances, inventory, games, relationships, and financial history | Removes operational state; anonymizes accounting rows that must remain internally consistent |
| UniMod | In-memory message buffers; optional redacted diagnostic response | Buffers vanish on unload; diagnostic files expire within one hour and are removed on unload/restart |
| VoiceNoteLog | Voice note audio sent to Google for transcription; the text is posted to a staff-only log channel with the author's name and ID | No local record; Google processes the audio transiently and the log messages follow Discord retention |

Configuration-only cogs do not retain per-user records. Some cogs send user-provided content to Discord or a configured external service; their metadata statements describe that processing even when the cog itself does not retain a copy.

## Financial audit records

Unicornia exports the complete available transaction history without a hardcoded row limit. On deletion, accounting rows are retained only when deleting them would invalidate the ledger. Direct user IDs and free-form metadata in those rows are replaced with a non-user sentinel or removed. Operation keys are replaced with unique internal deletion keys.

## Operator checklist

Before release, run the metadata contract test and the relevant deletion tests. When adding a new stored field, update the cog's `info.json`, this inventory, and its deletion/export implementation in the same change.
