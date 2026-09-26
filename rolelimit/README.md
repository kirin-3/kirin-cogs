# RoleLimit

> Fork of [colourlimit](https://github.com/jenjenjam/jencogs/tree/master/colourlimit) and
> [rolelimit](https://github.com/jenjenjam/jencogs/tree/master/rolelimit) by jenjam
> ([jencogs](https://github.com/jenjenjam/jencogs)), merged into one cog. Ported and released here under MIT with
> the permission of our dear friend jenjam, who wrote the originals for our server. jencogs has no license file,
> which is expected: this cog is covered by that permission.

Keeps members to one role out of a configured set. It has two independent lists:

- **Colour list** (`[p]colourlimit`): when a member gains a listed role, the listed roles they already had are removed,
  so the newest one stays.
- **Ranked list** (`[p]rolelimit`): a member keeps only the listed role that comes last in the list. Set the list lowest
  first.

Roles above the bot's top role are skipped, and nothing is removed when the bot lacks `Manage Roles`.

## Commands

All commands need administrator (or Red's admin role).

| Command | What it does |
| --- | --- |
| `[p]colourlimit set <roles...>` | Replace the colour list |
| `[p]colourlimit listroles` | Show the colour list |
| `[p]colourlimit clear` | Empty the colour list |
| `[p]rolelimit set <roles...>` | Replace the ranked list, lowest first |
| `[p]rolelimit listroles` | Show the ranked list |
| `[p]rolelimit clear` | Empty the ranked list |
| `[p]rolelimit scan` | Apply the ranked list to every member (asks for confirmation) |

## Migrating from jencogs

The cog reads the Config the originals saved (`ColourLimit` and `RoleLimit`, same identifiers), so nothing needs to be
set again. Unload and uninstall jencogs' `colourlimit` and `rolelimit`, then install and load this one.
