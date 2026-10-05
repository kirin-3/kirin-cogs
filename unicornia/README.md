# Unicornia

Unicornia is a full Nadeko-compatible leveling and economy suite in one cog, backed by its own SQLite database (`data/unicornia.db`, Nadeko schema v3+).

## Features

- **Currency**: Wallet and bank ("Slut points") with daily rewards and streaks, transfers, 5% rakeback on losses (blackjack excluded), transaction history, leaderboards, and configurable decay.
- **Currency Drops**: Currency "picks" planted in channels via `[p]pick`.
- **Gambling**: Betroll, RPS, slots, blackjack (with capped spectator wagers), coinflip, luckyladder, mines, and staked PvP rock-paper-scissors duels via `[p]duel @user <amount>`.
- **Leveling**: XP per message with rank cards, role and currency level rewards, double-XP channels, and per-guild channel whitelists.
- **XP Shop**: Background shop with purchasable rank-card backgrounds.
- **Shop**: Guild item/role shop, also posted in a shop channel as one Components V2 message per section, with a menu to buy from it (managed on the staff dashboard's Role shop page).
- **Clubs**: Create, join, and manage clubs with shared XP and leaderboards.
- **Waifus**: Claim, snipe, gift, divorce, and set affinity with other members.
- **Unicorn Stable**: An idle game with an image card: hatch unicorns of five rarities that earn coins while you're away, upgrade them, and collect the coin box — plus shinies (1 in 200), a permanent collection with per-breed perks, ascension for a full stable of level-10s, and seasonal eggs in their UTC windows, all also on the member site ([STABLE.md](STABLE.md)).
- **Nitro Shop**: Redeem Nitro boosted/basic rewards.
- **Stock Market**: IPOs, buy/sell with pricing and slippage, portfolios, stock-trade tax, dividends funded by a house yield pool (including realized gambling edge), and a persistent live Components V2 dashboard (`[p]stock dashboard`). Review history with `[p]stock dividends`.
- **Owner Tooling**: Global config, RTP/yield dashboard (`[p]unicornia yieldstats`), command/system whitelists, and market unwind.

## Requirements

- `aiosqlite`, `Pillow`, `PyYAML` (installed automatically from `info.json`)
- No external services; all data is local SQLite

## Documentation

- [COMMANDS.md](COMMANDS.md) — full command reference
- [API.md](API.md) — in-process API for other cogs (`apply_operation`, `add_balance`, ...)
- [ECONOMY.md](ECONOMY.md) / [LEVELING.md](LEVELING.md) / [STOCKS.md](STOCKS.md) / [WAIFU.md](WAIFU.md) / [STABLE.md](STABLE.md) / [XPSHOP.md](XPSHOP.md) / [DATABASE.md](DATABASE.md) — subsystem guides

## Quick Start

```
[p]load unicornia
[p]unicornia status
[p]balance
[p]daily
```

Most commands are hybrid (prefix and slash). Owner/config commands under `[p]unicornia` are prefix-only.
