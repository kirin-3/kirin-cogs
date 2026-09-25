# Kirin's Red Discord Bot Cogs

A collection of custom cogs for [Red Discord Bot](https://github.com/Cog-Creators/Red-DiscordBot).

The bot's [Privacy Policy](PRIVACY.md) covers the whole instance; [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md) is the per-cog data inventory behind it.

## Available Cogs

### AntiNuke
Server protection against rogue administrators: monitors destructive actions (mass deletions, bans, prunes, permission grants, vanity/bot changes) and automatically quarantines offenders, with a trust system and role restoration.

### AutoMod
Rule-based automod for Unicornia, replacing YAGPDB's: rulesets of triggers, conditions and effects on messages, edits, joins and name changes, with the harshest punishment winning and a dry-run mode. Staff view the rules and an action log on the staff site, and only the bot owner can edit them. See [automod/README.md](automod/README.md).

### BanLog
Keeps a rolling 7-day copy of Unicornia's messages and, on every ban, saves the banned member's messages into a permanent record, so messages purged by a ban can still be reviewed on the staff site. See [banlog/README.md](banlog/README.md).

### Confess
Confess secretly in a confession room using a button and modal system.

### ContestCog
Posts an interactive dashboard (Components V2) for Unicornia's Cutie of the Month (COTM) contest information, prizes, and voting instructions, with reaction-based vote counting and reward distribution.

### CustomCommand
Allows users with a specific role to create and manage their own single custom command.

### CustomEmoji
Allows users with a specific role to create and manage their own custom emojis.

### CustomRoleColor
Allows administrators to assign a role to a user and lets that user customize the color, name, and icon of their assigned role.

### Dashboard
Serves the staff web site `staff.unicornia.net` from inside the bot, behind Discord login for Unicornia staff with 2FA. Its first pages show BanLog's ban records. See [dashboard/README.md](dashboard/README.md).

### Honeypot
Trap channel that automatically bans fresh members or strips roles and times out established members who post in it.

### Moderation
Dated, paginated `[p]warnings`, role-strip mutes with automatic unmute, kicks, bans, unbans with a reinvite, and
`[p]userinfo`, each with a custom DM, plus a YAGPDB-style public mod-log. Replaces Red's Mod and Mutes cogs. See [moderation/README.md](moderation/README.md).

### NitroAward
Awards economy currency to users when they boost the server via the Unicornia cog.

### Patron
Syncs patron roles and awards currency from a Google Sheet (Patreon/BuyMeACoffee) using idempotent payments.

### Profile
Create and manage user profiles with interactive modals and sticky messages.

### Roleplay
Roleplay action commands (`[p]hug`, `[p]ask`, ...) with consent prompts and per-member settings: owners, allowed and blocked lists, and selective, public and servant flags. Ported from the Unicornia repo; its existing member settings carry over unchanged.

### RulesAccept
Lets users accept rules via a button and modal, automatically assigning a role upon acceptance.

### Suggest
A suggestion system that uses a sticky message with a button to submit suggestions and tracks votes.

### TabooAccess
Manages access to restricted content through a button and modal system, assigning appropriate roles upon acceptance.

### Tickets
Advanced single-panel Discord support ticket system with a verification flow.

### UnicornAI
Autonomous AI persona system using OpenAI-compatible endpoints (NanoGPT by default) for persona-based interactions.

### Unicornia
Full Nadeko-compatible leveling and economy suite (currency, banking, gambling, XP, shops, clubs, waifus, stocks) backed by SQLite, with migration support from an existing Nadeko database.

Unicornia includes stock dividends funded by realized gambling edge and stock-trade tax, player-versus-player
rock-paper-scissors through `[p]duel @user <amount>`, capped spectator wagering on live blackjack hands, and an
owner-only aggregate economy dashboard at `[p]unicornia yieldstats`. Users can review dividend history with
`[p]stock dividends`.

### UnicornSecurity
Channel filter that only allows tenor GIF links in a specific channel, deleting other image links.

### UniMod
AI-powered auto-moderation using sentiment analysis and AI detection to alert moderators of potential violations.

### VerifyUser
Allows authorized users to verify other members by granting them a specific verification role.

## Archived Cogs

These cogs live in [archived/](archived/). They are retired, no longer developed, and cannot be installed through `[p]cog install`.

- **UnicornDocs**: AI-powered documentation question and answer system for the moderation team using keyword retrieval and OpenRouter.
- **UnicornImage**: Text-to-image generation supporting both Stable Horde (free) and Modal (premium) backends.
- **YAGPDBImport**: Imports YAGPDB warnings into Red's Warnings cog.

## Installation

To install these cogs, run the following commands in Discord:

```
[p]repo add kirin-cogs https://github.com/kirin-3/kirin-cogs
[p]cog install kirin-cogs <cogname>
[p]load <cogname>
```

Replace `<cogname>` with the name of the cog you want to install. Each cog folder contains its own README with detailed setup instructions.

## Requirements

- Red Discord Bot V3 (3.5.22+)
- Python 3.11+
- discord.py 2.6+ (provided by Red)

## License

All cogs are released under the MIT License.
