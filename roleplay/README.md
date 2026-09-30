# Roleplay

Roleplay action commands (`[p]hug`, `[p]kiss`, ...) with a consent system and per-member settings: owners, allowed
and blocked lists, and selective, public and servant flags. Ported from the Unicornia repo (originally by Ruffiana);
existing member settings carry over unchanged, because the cog keeps its Config pinned to the same cog name and
identifier the old install used.

## Actions

Each action is a YAML file in `actions/`, which becomes both `[p]<action>` and `[p]roleplay <action>`, usable with a
target (`[p]hug @user`) or without one — with no target, the server's default member performs the action on you.
The bot needs **Embed Links** and **Attach Files** to post the result.

| Action | Aliases | Notes |
| --- | --- | --- |
| `bite`, `caress`, `cuddle`, `feed`, `grope` | gropes/fondle(s) | |
| `highfive` | highfives/high5 | |
| `holdhands` | | image sent as a spoiler |
| `hug` | hugs | |
| `happyhug` | hughappy/happyhugs | |
| `sadhug` | hugsad/sadhugs | |
| `kiss` | kisses/smooch | |
| `lick`, `pat`, `pet`, `poke`, `slap`, `spank`, `tickle` | | |
| `bow` | bows/bowto | no consent prompt |
| `smug` | | no consent prompt |
| `cunnilingus` | eatout/eatsout | spoilered |
| `fuck` | fucks/bang(s)/havesexwith | spoilered |
| `nipplesuck` | nipplesucks | spoilered |
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

## Images and pairings

Each action's gifs are the image files in the cog's data folder under `images/<action>/` (subfolders included). The
folder is read every time the action is used, so adding, renaming or deleting files needs no reload. An action with
no images still runs, without a gif. Spoilered actions always send their gif as a spoiler.

A file's **pairing** is the `mlw`, `wlm`, `wlw` or `mlm` part of its name, split on `_` (`hug_wlw_1234.gif`). Files
without one are untagged.

- `[p]hug @member` picks from the untagged, `mlw` and `wlm` gifs, never `wlw` or `mlm`.
- `[p]hug wlw @member` (any case, before the member, also `[p]ask hug wlw @member`) picks only `wlw` gifs. `mlw` and
  `wlm` are different pairings.
- If the action has no gifs for that pairing, a default one is used and the message notes it ("No wlw gifs for suck
  yet").

## Gifs on the member site

The member site's **Gifs** page (`my.unicornia.net/gifs`) lists every action with its number of gifs. Each action has
three pages, one per pool: **Default** (untagged, `mlw` and `wlm` gifs: the pool the bot picks from when no pairing is
asked for), **wlw** and **mlm**. A page shows 5 gifs, playing, ordered by filename. It reads the images folder as it is
when the page is opened, so file changes show up on the next load. Spoilered actions are shown like any other.
Members aren't shown file names. A gif with `eros` in its file name (any case, e.g. `hug_eros_1234.gif`) gets a small
**AI** badge, so name AI-made gifs that way.

- **Votes.** Every member can give a gif a thumbs up or a thumbs down, change it, or press the thumb again to take it
  back. A member sees only their own vote. The staff site's **Gif votes** page lists every gif that has a vote, with
  its thumbs-up and thumbs-down totals, lowest score first. Votes don't change which gif the bot picks.
- **Renaming a gif drops its votes.** A vote belongs to the action and the file name, so adding `_wlw_` to a name
  starts that gif over. Votes for a file that's gone stay stored, unseen, and come back if the name does.
- **Sending in a gif.** Members with the active supporter role (`700121551483437128`), the inactive one
  (`1458440559713718466`) or the Level 90+ role (`721360680770469958`) get a form on the Gifs pages to send in a GIF for
  an action. The bot posts it in the review channel (`1554813851302887494`) as one message naming the action and the
  member, without pinging them. That is all it does: staff review the gif, name it with its pairing and add it to the
  images folder by hand, and the bot keeps no copy. The file has to be a GIF (judged by its content, not its name) and
  no bigger than Discord lets the bot upload in that server. Each member can send one gif a minute.
- The bot needs **View Channel**, **Send Messages** and **Attach Files** in the review channel, or uploads answer that
  they're unavailable.

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
| `[p]<action> [pairing] [member]` | everyone (server-only) | Perform the action. Also `/<action>`, e.g. `/hug pairing:wlw member:@user` |
| `[p]roleplay <action> [pairing] [member]` | everyone | Same thing under the group |
| `[p]ask <action> [pairing] [member]` | everyone (server-only) | Ask a member to perform the action on you. Also `/ask`, which suggests the actions as you type |
| `[p]roleplay help` | everyone | Custom help embed listing settings and actions |
| `[p]roleplay settings [member]` | self; others need admin | Open the settings dashboard (behind a button, since only a button can answer ephemerally) |
| `/roleplay settings` | self | Open your settings dashboard right away, only to you |
| `[p]roleplay settings help` | everyone | Help for the settings commands |
| `[p]roleplay settings owners add/remove <user>` | everyone | Manage your owner list (one owner; adding asks them first). Alias `owner` |
| `[p]roleplay settings allowed add/remove <user>` | everyone | Manage your allowed list. Aliases `allow`, `approved`, `approve` |
| `[p]roleplay settings blocked add/remove <user>` | everyone | Manage your blocked list. Alias `block` |
| `[p]roleplay settings selective [member] [true/false]` | self; others need admin | Reject everyone not in your allowed list |
| `[p]roleplay settings public [member] [true/false]` | self; others need admin | Consent to any action from a member |
| `[p]roleplay settings servant [member] [true/false]` | self; others need admin | Consent to any request on you |
| `[p]roleplay settings untracked [member] [true/false]` | self; others need admin | Stop counting your actions and delete your counts |
| `[p]roleplay settings actions [add/remove <action> ...]` | everyone | Show or change the actions you always allow, e.g. `actions add hug pet`. Alias `always` |
| `[p]rpstats [member] [other]` | everyone (server-only) | Action counts: yours, a member's, or between two members. Also `/rpstats` once enabled |
| `[p]roleplay admin logger_settings [level]` | bot admin | Show or set the cog's log level |

`settings add/remove` commands delete the invoking message after 10 seconds, and help/settings embeds clean
themselves up after a few minutes. List settings resolve users by ID, mention, username or display name.
`remove` also works for listed users who have left every server the bot is in, by ID or by the name the list
shows, so a member whose owner left can remove them and add a new one.

The settings dashboard shows your settings with controls to change them. It's only visible to you, and only you
can use it:

- A button for each on/off setting (green is on).
- A user dropdown each for setting your owner and adding to your allowed and blocked lists. Setting an owner still
  asks them first, in the channel.
- A dropdown to remove anyone from your lists (the first 25; use the `remove` commands for more).
- An **Always Allowed Actions** button that opens a picker for the actions you consent to from anyone.

An admin who opens someone else's dashboard with `[p]roleplay settings @member` changes that member's settings.

**Always allowed actions** work like Public Use Slut for just those actions: anyone except your blocked members can
do them to you without asking, even when you're Selective. Everything else still asks. Your owner is still asked, and
being asked to do an action yourself (`[p]ask`) still asks you.

## Notes

- Settings are **user-scoped**: your lists and flags are the same in every server that shares this bot.
- Guild admins can view or toggle any member's settings; only the first owner in a member's owner list is used.
- Slash commands: every action, `/ask`, `/rpstats` and `/roleplay settings`. Aliases (`/hugsad`, ...) and the rest of
  `[p]roleplay` stay prefix-only. The owner enables them once with `[p]slash enablecog roleplay` and `[p]slash sync`.
  That is 33 of Discord's 100 global slash commands.

## Stats

Every action that goes through between two members is counted for the pair, the right way round: `[p]ask`ed
actions count for the member who performed them. Actions performed by the bot (no target) and refused or
unanswered ones aren't counted. Counting started with version 2.7.0, so earlier actions aren't included.

- `[p]rpstats` shows your totals and top actions, given and received, and your favourite partners.
  `[p]rpstats @member` shows theirs; `[p]rpstats @a @b` shows what each did to the other.
- The member site's Roleplay page shows the same for you, and the ten busiest pairs on the server.
- **Untracked Member** (`[p]roleplay settings untracked true`, or the switch on the member site) stops counting
  your actions both ways round, deletes everything already counted for you, and makes `rpstats` about you say
  your stats are private.

## Data storage and deletion

Per-user settings: the `selective`, `public`, `servant` and `untracked` flags, and the user IDs in each member's owner,
allowed and blocked lists, stored in Red Config under the pinned `Settings` cog name. Action counts: for each pair
of member user IDs, how many times one performed each action on the other, in the cog's own `Roleplay` Config. Gif
votes: for each voted gif (action and file name), the user IDs that voted it up or down, in the same Config. A gif
sent in on the member site is posted to the review channel and not stored. Red data-deletion requests clear a user's
own settings, counts and gif votes, and scrub their ID from every other member's lists and counts. Downloaded images live in the cog's
data folder and are not user data.
