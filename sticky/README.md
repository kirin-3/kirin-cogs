# Sticky

> Fork of [sticky](https://github.com/Tobotimus/Tobo-Cogs/tree/V3/sticky) by Tobotimus
> ([Tobo-Cogs](https://github.com/Tobotimus/Tobo-Cogs)). Licensed **GPL-3.0** like the original (see [LICENSE](LICENSE)),
> unlike the rest of this repo.

Sticks a message to the bottom of a channel: when someone posts, the bot reposts the sticky below them and deletes the old
copy. Deleting the sticky message makes the bot post it again; use `[p]unsticky` to remove it.

Fixes over the original:

- Deleting a message in a DM, thread or uncached channel no longer raises `AttributeError`.
- Replacing a sticky could post a duplicate or leave the old copy behind; the new message is now saved before the old one
  is deleted.
- Channels without a sticky are skipped after one Config read instead of taking a lock on every message.
- Missing permissions when reposting are logged instead of raised.

## Commands

All commands need `Manage Messages` or Red's mod role.

| Command | What it does |
| --- | --- |
| `[p]sticky <text>` | Sticky this text to the channel |
| `[p]sticky existing <message>` | Sticky an existing message's text and first embed (ID or link) |
| `[p]sticky toggleheader <true/false>` | Show or hide the "Stickied Message" header |
| `[p]sticky cooldown [seconds]` (alias `setcooldown`) | Wait at least this long between reposts (minimum and default 3). Omitting the seconds resets the cooldown to 3 |
| `[p]unsticky [yes]` | Remove the sticky; `yes` skips the confirmation |

## Migrating from Tobo-Cogs

The cog reads the Config the original saved (`Sticky`, same identifier), so every channel's sticky carries over. Unload
and uninstall Tobo-Cogs' `sticky`, then install and load this one.
