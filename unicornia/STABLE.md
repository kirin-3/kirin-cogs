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
| ✨ **Ascend** | Ascends a stable of ten level-10 unicorns, after a yes/no only you see. |
| **Upgrade a unicorn…** | Raises the chosen unicorn one level. |
| **Release a unicorn…** | Lets the chosen unicorn go, after a yes/no only you see. You get nothing back. |

Only the owner gets the buttons; `[p]stable @member` shows anyone's card. Buttons stop after 5 minutes; run the
command again. The rest: `[p]stable name`, `[p]stable release`, `[p]stable collection`, `[p]stable ascend` and
`[p]stable top` (see [COMMANDS.md](COMMANDS.md)).

## Earning

- A unicorn earns its rarity's rate × its level, per day, and 10% more if it is shiny:

  | Rarity | Chance | Coins a day per level | Breeds |
  | --- | --- | --- | --- |
  | Common | 50% | 10 | Cotton, Hazel |
  | Uncommon | 28% | 14 | Bluebell, Clover |
  | Rare | 15% | 18 | Rose Quartz, Twilight |
  | Epic | 6% | 25 | Ember, Frost |
  | Legendary | 1% | 35 | Celestial, Prism |

- The whole stable's earnings are multiplied by (1 + collection bonus + perk bonus + 10% per ascension), then by
  the owner-set `earn_rate`. The collection and perk bonuses cap at 15% and 25%.
- The box holds 8 hours of earnings at first, and 12, 16 or 24 hours after buying bigger boxes (5,000, 15,000 and
  40,000), plus any hours from box perks. A full box stops filling until it's collected. Nothing is ever lost or
  punished.
- A stable holds 10 unicorns. Releasing one frees a stall (and makes the next egg cheaper again), so players can
  keep hatching in the hope of a legendary — or to complete their collection.

## Shinies

About one hatch in 200 is a **shiny** version of its breed: a gold sparkle frame and badge on the card, ✨ in the
menus and messages, and 10% more earnings, permanently. Bluebell and Prism each double the shiny chance while in
the stable; both together make it one in 50. Releasing a shiny, or ascending a stable containing one, says so
before you confirm: the shiny is lost with the unicorn (though it stays in your collection).

## Collection

The stable remembers every breed you have ever hatched — separately for shinies — and that log survives releases
and ascensions. Discovering both breeds of a rarity adds 2% to the collection bonus, and all ten regular breeds
adds a further 5%, for a maximum of 15%. Seasonal breeds and shinies add nothing: they're for the collection's
own sake.

`[p]stable collection` lists the ten regular breeds grouped by rarity, then any seasonal breeds you've found.
Undiscovered breeds show as "???" — their names, perks and art stay secret until you hatch one. The card's header
shows how many you've found.

## Breed perks

Each regular breed has one perk, active while at least one unicorn of that breed is in your stable. A perk counts
once however many of that breed you hold, and releasing the last one switches it off.

| Breed | Perk |
| --- | --- |
| Cotton | The coin box holds 1 hour more. |
| Hazel | Level-ups cost 10% less. |
| Bluebell | Shiny chance is doubled. |
| Clover | Each egg has a 10% chance to cost nothing. |
| Rose Quartz | Eggs cost 5% less. |
| Twilight | The coin box holds 3 hours more. |
| Ember | The stable earns 5% more. |
| Frost | Rare, epic and legendary hatch chances are 1.5 times as high. |
| Celestial | The stable earns 10% more. |
| Prism | The stable earns 10% more and shiny chance is doubled. |

The earnings perks together cap at 25%. A free egg from Clover still requires you to be able to afford it — it
just doesn't take the coins, and says it was free.

## Ascension

Once all ten stalls hold level-10 unicorns you can **ascend**, from the card's Ascend button or
`[p]stable ascend`. Both ask first. Ascending pays the whole coin box into your wallet, your unicorns trot off,
and you keep your coins, your coin box size and your collection. Each ascension earns you 10% more — and raises
egg and level prices 20%, compounding, so each loop costs more than the last.

## Seasonal eggs

Four breeds exist only during their UTC hatch window, and nothing can make them hatchable outside it:

| Breed | Window |
| --- | --- |
| Pumpkin | 1 October – 2 November |
| Yule | 1 December – 6 January |
| Sweetheart | 1 – 21 February |
| Pride | 1 – 30 June |

During the window, each hatch has a 15% chance to produce the seasonal breed instead of the usual rarity roll.
Seasonal unicorns earn 25 coins a day per level, keep their teal frame colour, can be shiny like any breed, and
stay in your stable after the season ends. They have no perk and add nothing to the collection bonus. The card's
header mentions the active season, and they return every year.

## Prices

- Egg: 1,000 × 1.3 for every unicorn you already have (1,000, 1,300, 1,690 … about 10,600 for the tenth), × 1.2
  per ascension, less Rose Quartz's 5% while she's in the stable.
- Level: 100 × 1.4 for every level above 1 (100 to reach level 2, about 1,480 to reach level 10), × 1.2 per
  ascension, less Hazel's 10% while she's in the stable.
- A full stable of ten level-10 unicorns costs about 92,000 and earns about 1,350 a day on average rarities, 2–3×
  `timely`.
- Tuned against the live economy (September 2026): the 40 active players earn about 350 a day from timely, picks and
  level rewards and have a median balance of 6,500. Such a player fills a stable in about two and a half months,
  collecting each day. Rich players can build one at once: a one-off sink for an income that's capped.

The bot owner can tune these without a restart: `[p]stableset` shows the values and `[p]stableset <key> <value>`
changes one (`egg_price`, `egg_growth`, `level_price`, `level_growth`, `earn_rate`).

## Member site

`/me/stable` on my.unicornia.net shows the same card image, the earnings and box numbers, the ascension count,
your collection (undiscovered breeds as ???, and their art is never sent), your active perks and a **Collect**
button that works like the card's. Hatching, upgrades, releases and ascension stay in Discord.

## How it works

- Coins accrue from timestamps: every read or change brings the box up to date, so there's no background loop.
  Upgrades and hatches settle the box first, so the new rate only counts from then on.
- Every bonus folds into one `Modifiers` value (`systems/stable_system.py`) built from the stable's unicorns,
  discoveries and ascensions, so the card, the buttons, the commands and the member site all show the same numbers.
- Collecting and buying run in one database transaction with the wallet change, logged in the transaction history
  as `stable_collect`, `stable_egg`, `stable_upgrade`, `stable_box` and `stable_ascend`. Clover's free egg simply
  isn't charged. Coin decay applies as to any other coins.
- The card is drawn with Pillow in a thread (`systems/stable_card.py`) from the art in `data/stable/`; the shiny
  frame, glow, sparkles and badges are drawn over the sprites, not separate art.
- Tables: `Stable`, `StableUnicorn` and `StableDiscovery` (see [DATABASE.md](DATABASE.md)). Deleting a member's
  data removes all three.

## Art

The unicorn sprites and the stable background in `data/stable/` were made for this cog with an image model, in one
style, and can be replaced by files of the same names (square sprites, a 1000×600 background).

## Later

- Trading unicorns, expeditions, "box full" pings.
