# Responder

Auto-responses to trigger phrases. Ported from the Unicornia repo
([ruffiana/Unicornia](https://github.com/ruffiana/Unicornia), originally by Ruffiana, MIT).

It only answers in the channels listed in `const.SERVER_PERMISSIONS` (Unicornia's bot channels and Ruffiana's test
server), and it ignores bots, Red's blocklist and servers where the cog is disabled.

## Responders

| Trigger | Response | Cooldown |
| --- | --- | --- |
| `<topic> rate`, optionally followed by a mention or user ID | A rating embed for you or the mentioned member | none |
| `I'm ...` / `I am ...` at the start of a message | "Hi, ...! I'm your daddy...", with a chance that drops as the name gets longer | none |
| `long cat` / `short cat` (more `o`s grow or shrink it) | Long cat built from emojis | 120 s |
| `The Game` (case-sensitive) | "I just lost The Game." | 120 s |
| `(╯°□°)╯︵ ┻━┻` | `┬─┬ノ( º _ ºノ)` | none |

Admins skip cooldowns. Responders with a cooldown stay silent while it runs.

## Opting out

`[p]daddyoptout` (also `/daddyoptout`, once enabled with `[p]slash enable daddyoptout`) turns the daddy replies off
for you, and running it again turns them back on. Members can also switch it on the member site's Settings page,
`my.unicornia.net/settings`. Only opted-out members are stored; turning replies back on deletes the record.

### Rates

`[p]rates` (also `/rates`, once enabled with `[p]slash enable rates`) lists the topics and the channels they work in.

Built-in topics: `berry`, `bottom`, `brat`, `clown`, `cute`, `dimbo`, `dom`/`sub`, `emma`, `fish`, `gay`, `gremlin`,
`horny`, `pet`, `rich`, `simp`, `sleepy`, `stinky`, `sus`. Each answer is a reply to the asker, with the topic's colour,
an emoji bar (rainbow for `gay`, hearts for `cute`...), and a title and quip that change with the rating.

- Random ratings are the same for a member and topic all day, and reroll at midnight UTC. Nothing is stored.
- `dom`/`sub` is computed from the member's roles and `berry` is fixed per member. `cute` is always 100%.
- `horny` is the share of lewd actions (fuck, suck, ride, grope, spank...) in the member's Roleplay cog counts. `rich` is
  their Unicornia wallet plus bank on a log scale, where 1,000 is 50% and 1,000,000 is 100%. A member without counts
  (or with roleplay's Untracked setting on) gets the daily roll instead, as does everyone when the other cog isn't
  loaded.
- Several topics have per-member overrides hardcoded in their `responders/rate_*.py` file.

Any other topic is a supporter perk: admins and the supporter roles in `rate_anything.py` get a daily percentage with
a GIF from Tenor's search for the topic, falling back to the member's avatar if Tenor fails.

## Adding a responder

Drop a module in `responders/` with a `BaseTextResponder` subclass that sets `enabled = True`, `patterns` and
`respond()`. The cog loads every module in that folder on startup. A new rate topic is a `BaseRateResponder`
subclass registered in `RateResponder.rate_classes` in `responders/rate.py`. It sets `title`, `description`, `color`,
`bar_full` (a tuple, cycled) and `bar_empty`, and optionally `rating_overrides` tiers and `user_overrides`. An override's
`"rating"` key replaces the rating, and `None` hides the bar.
