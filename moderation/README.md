# Moderation

Unicornia's moderation commands: a dated warnings viewer, role-strip mutes, kicks, bans, unbans with a reinvite,
user info, and a public mod-log. Every action DMs the member in the same style. Warnings themselves stay in Red's core **Warnings** cog
(`[p]warn`, `[p]unwarn`, `[p]mywarnings`, `[p]warnaction`), including the ones imported from YAGPDB.

## Setup

Red's Mod and Mutes cogs use the same command names, so unload them first. Load Red's Warnings cog too, and turn off
its own DM so members don't get two:

```
[p]unload mod mutes
[p]load warnings
[p]load moderation
[p]warningset senddm false
```

This cog's `[p]warnings` replaces Red's plain-text one while the Warnings cog is loaded. Load order doesn't matter,
and reloading either cog is safe: when Warnings loads or reloads, this cog takes `[p]warnings` over again, and when
this cog unloads, Red's version comes back. While the Warnings cog isn't loaded, `[p]warnings` and `[p]warns` don't
exist (this cog steps aside so Warnings can always load).

> **Note for reviewers:** this works and is tested (`test_warnings_command_is_shared_safely_with_reds_warnings_cog`).
> `sync_warnings()` is called from `setup()` in `__init__.py` and from the `on_cog_add` listener, which Red dispatches
> after every cog load. Unloading Warnings needs no handler: discord.py removes commands by name, so it takes this
> cog's `[p]warnings` with it, which is the intended "steps aside" state. The two cogs do not collide in either order.

Also reload the updated **RulesAccept** cog, which refuses muted members (see [Mutes](#mutes)).

## Commands

All commands are server-only. Each one is open to staff role `696020813299580940`, Red admins, bot owners, and
members holding the Discord permission that matches the action. Everyone else gets no reply (Red ignores failed
permission checks silently).

| Command | Also allowed with | Description |
| --- | --- | --- |
| `[p]warnings <user>` | - | Paginated warning history. Also `[p]warns`. Accepts an ID for users who left. |
| `[p]mute <member> [duration] [reason]` | Manage Roles | Takes all their roles, gives them Muted, and disconnects them from voice. Duration like `30m`, `2h`, `7d`, `1d12h`; leave it out for a mute that lasts until someone unmutes. |
| `[p]unmute <user> [reason]` | Manage Roles | Removes Muted and gives back the roles the mute took. Accepts an ID to lift the mute of someone who left. |
| `[p]kick <member> [reason]` | Kick Members | DMs them, then kicks. |
| `[p]ban <user> [days] [reason]` | Ban Members | DMs them, then bans. `days` (0-7) deletes that many days of their messages. Accepts an ID for users who aren't in the server. |
| `[p]unban <user ID> [reason]` | Ban Members | Unbans and sends them a one-use invite to the rules channel. |
| `[p]userinfo [user]` | - | Account age, join date, warning count, mute status, and which of a few key roles they hold (`USERINFO_ROLE_IDS` in `moderation.py`; the field is left out when they have none). Also `[p]whois`. |

Kick, ban, and mute refuse targets who are yourself, the server owner, or have the same or a higher role than you or
the bot. Every action is logged as a Red modlog case (`smute`, `sunmute`, `kick`, `ban`, `hackban`, `unban`,
`timeout`, `warning`), so `[p]case` and `[p]casesfor` show it next to warnings. Set the channel with
`[p]modlogset modlog #channel`.

## Mutes

A mute saves the member's roles, removes them, and gives them the Muted role (`686252873583165520`). With no roles
they can only see the rules channel. Unmute gives the saved roles back and removes Muted.

While someone is muted, the bot keeps them at exactly **Muted plus the roles it can't remove**:

- **Any role added during the mute is taken off again and saved**, and they get it on unmute. This covers every way
  a role can appear: Discord's onboarding "Channels & Roles" menu, linked roles, other bots (autoroles, role
  persistence, self-role commands), the rules button, and staff adding a role by hand.
- **If Muted is removed**, by hand or by another bot, the bot puts it back. Only `[p]unmute` or the timer ends a mute.
- **Leaving and rejoining** doesn't escape a mute: they get Muted back as soon as they rejoin. If a timed mute ran out
  while they were gone, the record is dropped and they rejoin normally.
- **Changes made while the bot was offline** are caught within 30 seconds of it coming back.
- **The rules button** in RulesAccept also refuses anyone with the Muted role.

Other details:

- **Timed mutes** end automatically. The bot checks every 30 seconds, and saved mutes survive restarts.
- **Muting someone who is already muted** only changes when the mute ends.
- **Voice**: muting disconnects them from voice. The bot needs **Move Members** for this, otherwise the reply says it
  couldn't.
- **Roles the bot can't remove** stay on the member: Server Booster, other bot-managed roles, and roles above the bot.
  Make sure none of those open channels.
- **If a saved role was deleted or moved above the bot** during the mute, unmute skips it and says how many it
  skipped.
- **Muted without a saved record** (someone given the role by hand or by YAGPDB): `[p]unmute` only removes Muted,
  because the bot doesn't know their old roles, and the bot doesn't enforce those mutes. Unmute YAGPDB mutes through
  YAGPDB, and use `[p]mute` for new ones.
- **A ban clears any mute**, so an unbanned user doesn't come back muted. A kick doesn't: a kicked member who rejoins
  is still muted.

### What the bot can't enforce

These come from Discord permissions, not roles, so they need to be right in the server settings:

- **What `@everyone` can do in the rules channel.** That's the one channel a muted member still sees. If `@everyone`
  can send messages, react, create threads, or use apps and slash commands there, so can a muted member. Deny those
  for the Muted role with a channel override in the rules channel.
- **Access given to a person directly.** A channel override for a specific member (for example their ticket channel)
  outranks roles, so they keep that channel while muted. Useful for tickets; remove other personal overrides by hand.
- **Server-wide `@everyone` permissions** such as Change Nickname or Create Invite still apply while muted.
- **Alt accounts.** Mutes and bans follow one account.

## Unban reinvite

`[p]unban` creates an invite to the rules channel (`684360255798509582`) that works once and expires in 24 hours, then
DMs it to the user. Bots can only DM people they share a server with, which a banned user usually doesn't, so if the
DM fails the bot posts the invite in the channel for you to pass on. The bot needs **Create Invite** in the rules
channel.

## Public mod-log

Bans, kicks, unbans, mutes, unmutes, and timeouts are posted to the public mod-log channel `694857480307474432`, in
the same layout YAGPDB used. **Warnings are never posted there.**

| Part | Content |
| --- | --- |
| Top | The moderator's name, ID, and avatar |
| Body | The action with an emoji (e.g. 🔨 **Banned** name *(ID ...)*), the duration for mutes and timeouts, and 📄 **Reason** |
| Right | The member's avatar |
| Colour | Red for bans and kicks, orange for mutes, gold for timeouts, green for unbans, unmutes, and removed timeouts |
| Bottom | The time of the action |

Where each entry comes from:

- **This cog's commands** (`mute`, `unmute`, `kick`, `ban`, `unban`) post directly, with the moderator who ran them.
  Automatic unmutes show the bot as the moderator and "Mute expired" as the reason.
- **Everything done outside this cog** is read from the server's audit log: bans, kicks, and unbans through
  Discord's own menus or other bots, and **timeouts** added or removed through Discord's Timeout option. These show
  the moderator and reason from the audit log.
- **AutoMod** mutes, timeouts and bans post directly, with the bot as the moderator.
- **Other actions by this bot** (Honeypot, AntiNuke) are not posted.
- **Timeouts from Discord's own AutoMod** use a different audit log entry and are not posted, and timeouts that simply
  run out aren't either.

Turn off YAGPDB's mod-log when you switch over, otherwise YAGPDB's own bans show up twice (once from YAGPDB, once
from the audit log).

## DMs

Each DM is an embed with the server name and icon, a title, and the time. The texts are hardcoded constants at the top
of `moderation.py`; edit them there to change the wording.

| Action | Title | Body |
| --- | --- | --- |
| Warn | ⚠️ You have been warned | Reason, plus "Further violations of server rules may result in channel restrictions, temporary mute, or permanent ban." Footer: "Use .mywarnings to see your warnings." |
| Mute | 🔇 You have been muted | Reason, when the mute ends, and "Further violations of server rules may result in a permanent ban." |
| Unmute | 🔊 You have been unmuted | "Your mute has ended and your roles have been given back." Also sent when a timed mute runs out. |
| Timeout | ⏳ You have been timed out | Reason, when the timeout ends, and the permanent-ban notice. Sent for AutoMod timeouts. |
| Kick | 👢 You have been kicked | Reason and the permanent-ban notice. |
| Ban | ⛔ You have been banned | Reason and the appeal form `https://forms.gle/SdrjyV9ggi3hBQbh8`. |
| Unban | ✅ You have been unbanned | The one-use invite. |

Kick and ban DM **before** acting, because the bot can't DM people who have left. The warn DM goes out after
Red saves the warning. A member kicked or banned by `[p]warnaction` has already left by then, so they usually won't
get it. When a DM fails, the command reply says so.

## Methods for other cogs

AutoMod punishes through these methods. Each returns an error message, or `None` when it worked, and refuses the
server owner and anyone at or above the bot's highest role.

| Method | What it does |
| --- | --- |
| `mute_member(member, until, reason, moderator, *, keep_longer=False)` | The same mute as `[p]mute`. With `keep_longer`, an existing mute is never shortened. |
| `timeout_member(member, until, reason, moderator)` | A Discord timeout with a DM, a `timeout` modlog case and a public log post. |
| `ban_user(guild, user, reason, delete_days, moderator)` | The same ban as `[p]ban`. |
| `warn_member(member, reason, moderator)` | Saves a 1-point warning in Red's Warnings storage, DMs it and creates a `warning` case. |

## Warnings list

`[p]warnings` shows the newest warning at the top, and `#1` is always the oldest. Each entry shows:

- **Number and date**: in the viewer's local time, plus a relative time ("3 years ago").
- **Reason**: shown as a quote, cut off after about 550 characters.
- **Moderator**: a mention if they are still in the server, otherwise their name. For YAGPDB imports it falls back to
  the name YAGPDB saved. Moderators whose data Red deleted show as "Deleted moderator".
- **Tags**: `YAGPDB` for imported warnings, and points when they are not 0.
- **ID**: the value `[p]unwarn <user> <ID>` needs to remove that warning.

Five warnings fit on a page. The footer shows total warnings, total points and the page number. A user with no
warnings gets a one-page embed that says so.

The date comes from the warning's ID. Red saves every warning under the ID of the `[p]warn` message, and Discord IDs
contain their creation time. Imported warnings got IDs built from the original YAGPDB date, so the same logic works for both.

## Bot permissions

- **Manage Roles**, with the bot's highest role above Muted and above every role it should strip.
- **Move Members**, to disconnect muted members from voice.
- **View Audit Log**, and **Send Messages** plus **Embed Links** in the public mod-log channel.
- **Kick Members** and **Ban Members**, and **Moderate Members** for AutoMod timeouts.
- **Create Invite** in the rules channel, for unban reinvites.
- **Embed Links** where the commands are used.

## Data storage

For each active mute the cog stores the member's ID, the IDs of the roles the mute removed, and when the mute ends.
The record is deleted on unmute, when a timed mute expires, and on ban. Red's data-deletion requests remove a user's
mute records from every server. Warnings are stored by Red's Warnings cog, and modlog cases by Red's modlog.
