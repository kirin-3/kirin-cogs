# WarnList

WarnList sits on top of Red's core **Warnings** cog. It stores no data of its own: it reads and shows the warnings
that Warnings saves, including the ones imported from YAGPDB with `yagpdbimport`.

It does two things:

- Replaces `[p]warnings` with a paginated embed that shows each warning's date.
- Sends its own DM to a member after `[p]warn`, in place of Red's.

## Setup

Load WarnList **after** the Warnings cog, then turn off Red's own warn DM so members don't get two:

```
[p]load warnings
[p]load warnlist
[p]warningset senddm false
```

On load, WarnList takes Red's `[p]warnings` command and puts it back when unloaded. If you reload the Warnings cog,
reload WarnList afterwards, otherwise Red's plain-text `[p]warnings` comes back.

## Commands

| Command | Who | Description |
| --- | --- | --- |
| `[p]warnings <user>` | Admins | Paginated warning history. Also works as `[p]warns`. Accepts a mention, name, or user ID (IDs work for users who left). |

Everything else (`[p]warn`, `[p]unwarn`, `[p]mywarnings`, `[p]warningset`, `[p]warnaction`) is Red's Warnings cog,
unchanged.

### What the list shows

The newest warning is at the top, and `#1` is always the oldest. Each entry shows:

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

## Warn DM

After `[p]warn` saves a warning, the member gets this DM as an embed:

> You have been warned in the Unicornia Server for the following reason:
> *(reason)*
>
> **Further violations of server rules may result in channel restrictions, temporary mute, or permanent ban.**
>
> Use .mywarnings to see your warnings.

- The text is the hardcoded `WARN_DM` constant in `warnlist.py`; edit it there to change the wording.
- No DM is sent when Red refuses the warn (warning yourself, a bot, the owner, an unknown reason).
- If the DM can't be delivered, the bot says so in the channel where `[p]warn` was used.
- Red runs automatic punishments (`[p]warnaction`) before this DM goes out. A member who gets kicked or banned
  by a warn action has left the server by then, so they usually won't receive it.

## Permissions

- `[p]warnings` uses Red's admin check, same as the original. Members without it get no reply (Red ignores failed
  permission checks silently). To let other roles use it, see `[p]permissions`.
- The bot needs **Embed Links** in channels where `[p]warnings` is used.

## Data storage

WarnList stores nothing. Warnings live in Red's Warnings cog, which handles their retention and deletion.
