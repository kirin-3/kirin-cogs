# AutoMod

Rule-based automod for Unicornia, replacing YAGPDB's. Staff read the rules and the action log on
`staff.unicornia.net` (the Dashboard cog); only a bot owner can change them there.

## How rules work

- A **ruleset** has a name, an enabled switch, conditions, and rules. A **rule** has triggers, conditions and effects.
- A rule fires when **any** of its triggers matches and **every** condition holds, its ruleset's included.
- **Triggers:**
  - message text: regex match, regex no-match, word list;
  - message contents: server invite, any link (`http(s)://`, `www.`, or a bare `discord.gg/...` invite; other bare
    domains don't count), mentions of
    distinct users and roles;
  - unsafe link: a link Google Web Risk lists as phishing, malware or unwanted software. Only links in messages a
    rule with this trigger applies to are looked up, at most 5 per message; server invites and the trusted sites
    below are never looked up, and a result is reused for 10 minutes. If the lookup fails or no API key is set, the
    link counts as safe and the bot logs a warning at most every 10 minutes;
  - counted over a window of 1 to 3600 seconds: messages, identical messages, attachments, links, mentions. Messages
    in channels the rule's channel conditions exclude don't count, and a member's counts start again from zero after
    one of these fires. Identical messages are counted the way YAGPDB counts them: case and outer spaces don't
    matter, other messages in between are skipped, messages with no text (images, stickers) match each other, and a
    message with a different number of attachments ends the run;
  - names (checked on join and on every nickname, display name or username change): name regex, name word list.
- **Conditions:** ignore bots, ignore roles, require roles (any or all), ignore channels, only in channels, new
  messages only, edits only. A thread counts as its parent channel too.
- **Effects:** delete, warn, mute (0 minutes = until unmuted), timeout, ban, set nickname, send message.
  A send message text can use `{user}` (the member, shown without a ping), `{user_id}`, `{channel}`, `{rule}`
  (ruleset / rule) and `{message}` (the message text in a code block, so its links can't be clicked; empty for joins
  and name changes). "Mention the member" adds a ping in front.
- **Harshest punishment wins.** When several rules fire on one event, only the harshest rule's punishments run:
  ban > mute > timeout > warn > set nickname, and longer beats shorter. Every fired rule's delete and send message
  effects still run, and the message is deleted once.
- Text is converted from fancy Unicode letters (math script, full-width) to plain letters, and invisible characters
  (zero-width space, soft hyphen) are removed, before matching. Word lists compare whole words without regard to
  case; an entry of several words, such as `kill yourself` or `don't`, matches only those words in that order. A
  regex that takes longer than 100 ms counts as no match, and a regex no-match trigger with a slow pattern stays silent — the timeout is treated as a match.
- Warns, mutes, timeouts and bans go through the Moderation cog, so they send the usual DMs, create modlog cases and
  post to the public mod-log. An automod mute never shortens a mute that is already running.

**Level roles:** rules such as "Newb to Silver" assume each member holds exactly one level role. RoleLimit enforces
that today; if that moves into the XP cog, it must keep doing so.

## Setup

1. Load `automod` and `moderation`. AutoMod starts with no rules and with dry-run on.
2. Import rules: DM the bot `[p]automod import` with the rules JSON file attached. The file holds the word lists, so
   don't post it in a server channel; if you do, the bot deletes your message after importing.
3. Watch the Automod log on the staff site. While dry-run is on, it shows what automod *would* do.
4. Switch dry-run off on the staff site.
5. For unsafe link triggers: enable the Web Risk API in a Google Cloud project, create an API key restricted to it,
   and set it with `[p]set api google_webrisk api_key,<key>`. The first 100,000 lookups a month are free; cap the
   API's daily quota in the Cloud console so a busy month can't go past that.

An import replaces every ruleset and list, including edits made on the staff site, so run `[p]automod export` first.
It leaves dry-run as it is.

## Commands (bot owner)

| Command | What it does |
| --- | --- |
| `[p]automod import` | Replace all rules and lists with the attached JSON file, after checking all of it. The attachment must be at most 2 MB. |
| `[p]automod export` | DM you all rules and lists as `automod-rules.json`. |

Everything else is edited on the staff site. Unloading the cog stops automod at once.

## Required bot permissions

Manage Messages, Manage Roles, Moderate Members, Ban Members and Manage Nicknames, plus the members intent for name
checks. A member at or above the bot's highest role can't be punished; the log records the failure.

## Hardcoded values

| Setting | Value |
| --- | ---: |
| Guild | `684360255798509578` |
| Action log | newest 250 entries |
| Regex time limit | 100 ms |
| Counted history | 100 messages per member per channel (tracked separately for each channel) |
| Unsafe link lookups | at most 5 links per message, results reused for 10 minutes |
| Trusted sites (never looked up) | discord.com, discord.gg, discordapp.com, discordapp.net, tenor.com, giphy.com, youtube.com, youtu.be, unicornia.net and their subdomains |

## Storage and data deletion

Red Config holds the rules, the lists, the dry-run switch and the action log. A log entry holds the time, the member's
ID and name, the channel, the rules that fired and the actions, but no message text. Counts for counted triggers are
kept in memory only. Links checked by an unsafe link trigger are sent to Google Web Risk without the member's ID or
the rest of the message; the results are cached in memory by link only.

Every Red data-deletion request removes the user's log entries and counts. Rules and lists hold no user data.
