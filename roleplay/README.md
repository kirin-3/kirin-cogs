# Roleplay

Roleplay action commands (`[p]hug`, `[p]kiss`, ...) with a consent system and per-member settings: owners, allowed
and blocked lists, and selective, public and servant flags. Ported from the Unicornia repo (originally by Ruffiana);
existing member settings carry over unchanged, because the cog keeps its Config pinned to the same cog name and
identifier the old install used.

## Actions

Each action is a YAML file in `actions/`, which becomes both `[p]<action>` and `[p]roleplay <action>`, usable with a
target (`[p]hug @user`) or without one — with no target, the server's default member performs the action on you.
The bot needs **Embed Links** to post the result.

| Action | Aliases | Notes |
| --- | --- | --- |
| `bite`, `caress`, `cuddle`, `feed`, `grope` | gropes/fondle(s) | |
| `highfive` | highfives/high5 | |
| `holdhands` | | image sent as a spoiler |
| `hug` | hugs | |
| `kiss` | kisses/smooch | |
| `lick`, `pat`, `pet`, `poke`, `slap`, `spank`, `tickle` | | |
| `bow` | bows/bowto | no consent prompt |
| `smug` | | no consent prompt |
| `cunnilingus` | eatout/eatsout | spoilered |
| `fuck` | fucks/bang(s)/havesexwith | spoilered |
| `peg` | pegs/strapon | spoilered |
| `ride`, `siton` (sitsons/sitonface/sitsonface) | | spoilered |
| `suck` | sucks/bj/blowjob | spoilered |
| `tuckin` | tucksin | |
| `uppies` | up/pickup/lift/liftup | |
| `walk` | walkies | |

Actions are also **asked for**: `[p]ask <action> [@member]` (aliases `askfor`, `get`, `giveme`, `gimme`, `request`)
asks another member to perform the action on you, with the same consent rules. `ask` has no cooldown.

- Action commands have a cooldown of one use per **120 seconds per channel**, reset when an interaction fails.
- All action commands are server-only.
- Images come from external hosts (weeb.sh, imgur, tenor, …). `[p]roleplay admin download` caches them into the
  cog's data folder and switches the cog to the local copies.

## Consent

Whether an action needs a Yes/No consent prompt (60 seconds, only the asked member may answer) is decided in this
order:

1. If either member blocked the other, the action is refused outright.
2. If the invoker is the target's owner, or in the target's allowed list, the action is allowed with no prompt.
3. Bots are never asked; members acting on themselves through `ask` are never asked.
4. A **selective** target refuses everyone not covered by the rules above.
5. Otherwise consent is needed, unless the target is **public** (for actions on them) or a **servant** (for requests
   to them), or the action has consent disabled (`bow`, `smug`).
6. When consent is needed, the target's **owner** is asked and answers for them, together with the invoker's own
   owner (unless that is the target).

## Commands

| Command | Who | What it does |
| --- | --- | --- |
| `[p]<action> [member]` | everyone (server-only) | Perform the action |
| `[p]roleplay <action> [member]` | everyone | Same thing under the group |
| `[p]ask <action> [member]` | everyone (server-only) | Ask a member to perform the action on you |
| `[p]roleplay help` | everyone | Custom help embed listing settings and actions |
| `[p]roleplay settings [member]` | self; others need admin | Show a member's consent settings (button, ephemeral) |
| `[p]roleplay settings help` | everyone | Help for the settings commands |
| `[p]roleplay settings owners add/remove <user>` | everyone | Manage your owner list (one owner; adding asks them first). Alias `owner` |
| `[p]roleplay settings allowed add/remove <user>` | everyone | Manage your allowed list. Aliases `allow`, `approved`, `approve` |
| `[p]roleplay settings blocked add/remove <user>` | everyone | Manage your blocked list. Alias `block` |
| `[p]roleplay settings selective [member] [true/false]` | self; others need admin | Reject everyone not in your allowed list |
| `[p]roleplay settings public [member] [true/false]` | self; others need admin | Consent to any action from a member |
| `[p]roleplay settings servant [member] [true/false]` | self; others need admin | Consent to any request on you |
| `[p]roleplay admin download` | bot admin | Cache all action images locally |
| `[p]roleplay admin logger_settings [level]` | bot admin | Show or set the cog's log level |

`settings add/remove` commands delete the invoking message after 10 seconds, and help/settings embeds clean
themselves up after a few minutes. List settings resolve users by ID, mention, username or display name.

## Notes

- Settings are **user-scoped**: your lists and flags are the same in every server that shares this bot.
- Guild admins can view or toggle any member's settings; only the first owner in a member's owner list is used.
- `[p]roleplay` itself is prefix-only; there are no slash commands.

## Data storage and deletion

Per-user settings only: the `selective`, `public` and `servant` flags, and the user IDs in each member's owner,
allowed and blocked lists, stored in Red Config under the pinned `Settings` cog name. Red data-deletion requests
clear a user's own settings and scrub their ID from every other member's lists. Downloaded images live in the cog's
data folder and are not user data.
