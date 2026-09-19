# Unicornia

Unicornia is a full Nadeko-compatible leveling and economy suite in one cog, backed by its own SQLite database (`data/unicornia.db`, Nadeko schema v3+). It can migrate data from an existing Nadeko `nadeko.db` via `[p]unicornia migration setpath` / `[p]unicornia migration run`.

## Features

- **Currency**: Wallet and bank ("Slut points") with daily rewards and streaks, transfers, 5% rakeback on losses (blackjack excluded), transaction history, leaderboards, and configurable decay.
- **Currency Drops**: Currency "picks" planted in channels via `[p]pick`.
- **Gambling**: Betroll, RPS, slots, blackjack (with capped spectator wagers), coinflip, luckyladder, mines, and staked PvP rock-paper-scissors duels via `[p]duel @user <amount>`.
- **Leveling**: XP per message with rank cards, role and currency level rewards, double-XP channels, and per-guild channel whitelists.
- **XP Shop**: Background shop with purchasable rank-card backgrounds.
- **Shop**: Guild item/role shop.
- **Clubs**: Create, join, and manage clubs with shared XP and leaderboards.
- **Waifus**: Claim, snipe, gift, divorce, and set affinity with other members.
- **Nitro Shop**: Redeem Nitro boosted/basic rewards.
- **Stock Market**: IPOs, buy/sell with pricing and slippage, portfolios, stock-trade tax, dividends funded by a house yield pool (including realized gambling edge), and a persistent live Components V2 dashboard (`[p]stock dashboard`). Review history with `[p]stock dividends`.
- **Owner Tooling**: Global config, RTP/yield dashboard (`[p]unicornia yieldstats`), command/system whitelists, market unwind, and Nadeko migration.

## Requirements

- `aiosqlite`, `Pillow`, `PyYAML` (installed automatically from `info.json`)
- No external services; all data is local SQLite

## Documentation

- [COMMANDS.md](COMMANDS.md) — full command reference
- [API.md](API.md) — in-process API for other cogs (`apply_operation`, `add_balance`, ...)
- [ECONOMY.md](ECONOMY.md) / [LEVELING.md](LEVELING.md) / [STOCKS.md](STOCKS.md) / [WAIFU.md](WAIFU.md) / [XPSHOP.md](XPSHOP.md) / [DATABASE.md](DATABASE.md) — subsystem guides

## Quick Start

```
[p]load unicornia
[p]unicornia status
[p]balance
[p]daily
```

Most commands are hybrid (prefix and slash). Owner/config commands under `[p]unicornia` are prefix-only.
