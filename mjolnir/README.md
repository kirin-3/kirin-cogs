# Mjolnir

> Fork of [mjolnir](https://github.com/Kreusada/Kreusada-Cogs/tree/ff9693e10f1d620f906b82d53c0949e0a96f0aab/mjolnir) by
> Kreusada ([Kreusada-Cogs](https://github.com/Kreusada/Kreusada-Cogs)), originally written by Jojo
> ([JojoCogs](https://github.com/Just-Jojo/JojoCogs)), MIT. Kreusada removed it from the repo in 2022; the link points to
> the last commit that had it.

Try to lift Thor's hammer. Each attempt has about a 6% chance; successful lifts are counted per user across all servers.

The leaderboard now uses the bot's user cache instead of fetching every user from Discord (the original made one API call
per user and failed if any of them had deleted their account), and pages with Red's button menu.

## Commands

All commands work in servers only.

| Command | What it does |
| --- | --- |
| `[p]trylift` | Try to lift the hammer (once a minute) |
| `[p]lifted` | Show how many times you've lifted it |
| `[p]liftedboard` | Show the leaderboard |

## Migrating from Kreusada-Cogs

The cog reads the Config the original saved (`Mjolnir`, same identifier), so everyone's lift counts carry over. Unload
and uninstall Kreusada's `mjolnir`, then install and load this one.
