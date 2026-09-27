# Unicorn Stable

An idle game in Unicornia. Unicorns earn coins into your stable's **coin box** while you're away; you collect the
box, hatch more unicorns and level them up. Everything costs more as you go, so the stable both pays out and soaks
up coins.

`[p]stable` shows your stable as an image card with buttons:

| Button | What it does |
| --- | --- |
| 💰 **Collect** | Moves the box's coins into your wallet. |
| 🥚 **Hatch egg** | Buys an egg; it hatches straight away into a unicorn of a random rarity. |
| 📦 **Bigger box** | Buys the next coin box size. |
| **Upgrade a unicorn…** | Raises the chosen unicorn one level. |
| **Release a unicorn…** | Lets the chosen unicorn go, after a yes/no only you see. You get nothing back. |

Only the owner gets the buttons; `[p]stable @member` shows anyone's card. Buttons stop after 5 minutes; run the
command again. The rest: `[p]stable name`, `[p]stable release`, `[p]stable top` (see [COMMANDS.md](COMMANDS.md)).

## Earning

- A unicorn earns its rarity's rate × its level, per day:

  | Rarity | Chance | Coins a day per level | Breeds |
  | --- | --- | --- | --- |
  | Common | 50% | 10 | Cotton, Hazel |
  | Uncommon | 28% | 14 | Bluebell, Clover |
  | Rare | 15% | 18 | Rose Quartz, Twilight |
  | Epic | 6% | 25 | Ember, Frost |
  | Legendary | 1% | 35 | Celestial, Prism |

- The box holds 8 hours of earnings at first, and 12, 16 or 24 hours after buying bigger boxes (5,000, 15,000 and
  40,000). A full box stops filling until it's collected. Nothing is ever lost or punished.
- A stable holds 10 unicorns. Releasing one frees a stall (and makes the next egg cheaper again), so players can
  keep hatching in the hope of a legendary.

## Prices

- Egg: 1,000 × 1.3 for every unicorn you already have (1,000, 1,300, 1,690 … about 10,600 for the tenth).
- Level: 100 × 1.4 for every level above 1 (100 to reach level 2, about 1,480 to reach level 10).
- A full stable of ten level-10 unicorns costs about 92,000 and earns about 1,350 a day on average rarities, 2–3×
  `timely`.
- Tuned against the live economy (September 2026): the 40 active players earn about 350 a day from timely, picks and
  level rewards and have a median balance of 6,500. Such a player fills a stable in about two and a half months,
  collecting each day. Rich players can build one at once: a one-off sink for an income that's capped.

The bot owner can tune these without a restart: `[p]stableset` shows the values and `[p]stableset <key> <value>`
changes one (`egg_price`, `egg_growth`, `level_price`, `level_growth`, `earn_rate`).

## How it works

- Coins accrue from timestamps: every read or change brings the box up to date, so there's no background loop.
  Upgrades and hatches settle the box first, so the new rate only counts from then on.
- Collecting and buying run in one database transaction with the wallet change, logged in the transaction history
  as `stable_collect`, `stable_egg`, `stable_upgrade` and `stable_box`. Coin decay applies as to any other coins.
- The card is drawn with Pillow in a thread (`systems/stable_card.py`) from the art in `data/stable/`.
- Tables: `Stable` and `StableUnicorn` (see [DATABASE.md](DATABASE.md)). Deleting a member's data removes both.

## Art

The unicorn sprites and the stable background in `data/stable/` were made for this cog with an image model, in one
style, and can be replaced by files of the same names (square sprites, a 1000×600 background).

## Later

- Prestige: release the whole stable for a permanent earnings bonus.
- Breed perks, seasonal eggs, trading unicorns.
