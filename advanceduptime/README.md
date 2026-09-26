# AdvancedUptime

> Fork of [advanceduptime](https://github.com/Kreusada/Kreusada-Cogs/tree/db751a8aed3d0fe7a426feb3e20a0047f4cc3d40/advanceduptime)
> by Kreusada ([Kreusada-Cogs](https://github.com/Kreusada/Kreusada-Cogs)), MIT. Kreusada removed it from the repo in
> 2023; the link points to the last commit that had it.

Replaces Red's `[p]uptime` with an embed that also shows system uptime, bot stats, latency and command usage since the
cog loaded. Unloading the cog brings the core command back.

The original crashed on every use with discord.py 2 (`bot.user.avatar_url` no longer exists); this fork fixes that.

## Commands

| Command | Who | What it does |
| --- | --- | --- |
| `[p]uptime` | everyone | Show the uptime embed |
| `[p]uptimeset botstats <true/false>` | owner | Show users, servers, owner and command count |
| `[p]uptimeset latencystats <true/false>` | owner | Show gateway and shard latency |
| `[p]uptimeset sysuptime <true/false>` | owner | Show the host's uptime |
| `[p]uptimeset usagestats <true/false>` | owner | Track and show the most and least used commands |
| `[p]uptimeset settings` | owner | Show these settings |

Command usage is kept in memory only and resets when the cog reloads.

## Migrating from Kreusada-Cogs

The cog reads the Config the original saved (`AdvancedUptime`, same identifier). Unload and uninstall Kreusada's
`advanceduptime`, then install and load this one.
