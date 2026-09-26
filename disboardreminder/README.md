# DisboardReminder

> Fork of [disboardreminder](https://github.com/phenom4n4n/phen-cogs/tree/master/disboardreminder) by phenom4n4n
> ([phen-cogs](https://github.com/phenom4n4n/phen-cogs), archived), MIT.

Thanks whoever bumps the server on Disboard, then reminds the bump channel two hours later.

Changes from the original:

- A bump is recognised by the image on Disboard's success embed, which is the same in every language, instead of the
  deprecated `Message.interaction` field.
- Messages use simple placeholders instead of TagScript, so the TagScript, rapidfuzz and unidecode requirements are
  gone. Embeds in messages are no longer supported.
- A missing channel or permission is logged instead of silently clearing the setting.

## Commands

All commands need `Manage Server` or Red's admin role. The alias `[p]bprm` also works.

| Command | What it does |
| --- | --- |
| `[p]bumpreminder channel [channel]` | Set the channel for thank-yous and reminders, or turn the cog off |
| `[p]bumpreminder pingrole [role]` | Role to ping with the reminder, or clear it (needs `Mention Everyone`) |
| `[p]bumpreminder message [text]` | Set the reminder text, or reset it |
| `[p]bumpreminder thankyou [text]` | Set the thank-you text, or reset it (alias `ty`) |
| `[p]bumpreminder clean [true/false]` | Delete Disboard's failed-bump replies in the bump channel |
| `[p]bumpreminder lock [true/false]` | Lock the bump channel after a bump, unlock it for the reminder (needs `Manage Roles`) |
| `[p]bumpreminder settings` | Show the settings and the next bump time |

Placeholders: `{member}`, `{member(mention)}`, `{member(id)}` and `{member(name)}` for the bumper (thank-you message
only), and `{server}`, `{server(id)}` and `{server(name)}` for the server (`{guild}` works too).

## Migrating from phen-cogs

The cog reads the Config the original saved (`DisboardReminder`, same identifier). Unload and uninstall phen-cogs'
`disboardreminder`, then install and load this one. Bump counts saved by older versions of the original are kept but not
shown; a user's count is deleted when they ask for their data to be removed.
