# ConversationGames

> Fork of the conversationgames cog from [Jintaku-Cogs-V3](https://github.com/Jintaku/Jintaku-Cogs-V3/tree/master/conversationgames)
> by Jintaku, rewritten for Unicornia. Licensed **AGPL-3.0** like the original (see [LICENSE](LICENSE)), unlike the
> rest of this repo.

Truth or dare, would you rather and never have I ever. The questions are the list Unicornia's copy of the original cog
had been curated to, a batch of spicier kink-flavoured ones added since (all in `questions.py`), and whatever
members suggest and staff approve. Some dares use the bot's `&` roleplay, `compat` and `rpstats` commands, so the
roleplay consent prompts still apply.

## Commands

| Command | Who | What it does |
| --- | --- | --- |
| `[p]truth [member]` | everyone | A truth, for `member` (pinged) or for whoever wants it |
| `[p]dare [member]` | everyone | A dare, the same way |
| `[p]truthordare [member]` | everyone | A random truth or dare. Alias `tod` |
| `[p]wouldyourather` | everyone | Would you rather, with live votes. Alias `wyr` |
| `[p]neverhaveiever` | everyone | Never have I ever, with live "I have" / "I haven't" counts. Alias `nhie` |
| `[p]cgset reviewchannel [channel]` | admin or Manage Server | Where member suggestions go; leave the channel out to stop taking them |

All are server-only. The five game commands are hybrid, so they work as slash commands once enabled with
`[p]slash enable <command>`. The bot needs **Embed Links**.

## Cards

- **Truth and dare cards** have Truth, Dare and Random buttons. Whoever presses one gets a new card of their own,
  so the game keeps going without typing.
- **Would you rather and never have I ever cards** have two vote buttons with live counts. Everyone gets one vote,
  can move it, and takes it back by pressing their choice again. Another deals a new card.
- Every card has **Suggest one** for suggesting a question of the same kind.
- Buttons stop working after 15 minutes; vote counts stay on the card.
- Each server draws from its own shuffled deck per game, so no question repeats until the whole deck has been
  drawn. Decks live in memory, so a restart reshuffles them.

## Suggestions

**Suggest one** opens a form: one line for truths, dares and never have I ever, two options for would you rather.
Leading "Would you rather", "or" and "Never have I ever" are trimmed, so members can type it either way.

Suggestions are posted to the review channel, with the member's mention, and Approve and Deny buttons that keep
working across restarts. Only members with Manage Server or Red's mod or admin roles can press them. An approved
question joins the server's decks straight away. Duplicates of questions already in the deck are refused.

Without a review channel, members are told suggestions aren't open.

## Data

Approved questions are stored per server, without who suggested them. Votes are counted in memory while a card is
live. Nothing is stored per member.

## Moving from Jintaku's cog

Both cogs are named `conversationgames` and have the same commands, so uninstall the original before installing
this one: `[p]cog uninstall conversationgames`, then `[p]cog install kirin-cogs conversationgames`. Its questions were
defaults in its code rather than Config, and they're all here.
