# Responder

Auto-responses to trigger phrases, with no commands. Ported from the Unicornia repo
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

### Rates

Built-in topics: `berry`, `bottom`, `cute`, `dimbo`, `dom`/`sub`, `emma`, `fish`, `gay`, `stinky`. Several have
per-member overrides hardcoded in their `responders/rate_*.py` file. `dom` is computed from the member's roles, and
`berry` is fixed per member.

Any other topic is a supporter perk: admins and the supporter roles in `rate_anything.py` get a random percentage with
a GIF from Tenor's search for the topic, falling back to the member's avatar if Tenor fails.

## Adding a responder

Drop a module in `responders/` with a `BaseTextResponder` subclass that sets `enabled = True`, `patterns` and
`respond()`. The cog loads every module in that folder on startup. A new rate topic is a `BaseRateResponder`
subclass registered in `RateResponder.rate_classes` in `responders/rate.py`.
