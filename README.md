# Kirin's Red Discord Bot Cogs

A collection of custom cogs for [Red Discord Bot](https://github.com/Cog-Creators/Red-DiscordBot).

The bot's [Privacy Policy](PRIVACY.md) covers the whole instance; [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md) is the per-cog data inventory behind it.

## Available Cogs

### AntiNuke
Server protection against rogue administrators: monitors destructive actions (mass deletions, bans, prunes, permission grants, vanity/bot changes) and automatically quarantines offenders, with a trust system and role restoration.

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

### Honeypot
Trap channel that automatically bans fresh members or strips roles and times out established members who post in it.

### NitroAward
Awards economy currency to users when they boost the server via the Unicornia cog.

### Patron
Syncs patron roles and awards currency from a Google Sheet (Patreon/BuyMeACoffee) using idempotent payments.

### Profile
Create and manage user profiles with interactive modals and sticky messages.

### RulesAccept
Lets users accept rules via a button and modal, automatically assigning a role upon acceptance.

### Suggest
A suggestion system that uses a sticky message with a button to submit suggestions and tracks votes.

### TabooAccess
Manages access to restricted content through a button and modal system, assigning appropriate roles upon acceptance.

### Tickets
Advanced single-panel Discord support ticket system with a verification flow.

### UnicornAI
Autonomous AI persona system using Vertex AI or OpenAI-compatible endpoints for persona-based interactions.

### UnicornDocs
AI-powered documentation question and answer system for moderation team using keyword retrieval and OpenRouter.

### Unicornia
Full Nadeko-compatible leveling and economy suite (currency, banking, gambling, XP, shops, clubs, waifus, stocks) backed by SQLite, with migration support from an existing Nadeko database.

Unicornia includes stock dividends funded by realized gambling edge and stock-trade tax, player-versus-player
rock-paper-scissors through `[p]duel @user <amount>`, capped spectator wagering on live blackjack hands, and an
owner-only aggregate economy dashboard at `[p]unicornia yieldstats`. Users can review dividend history with
`[p]stock dividends`.

### UnicornImage
Text-to-image generation supporting both Stable Horde (free) and Modal (premium) backends.

### UnicornSecurity
Channel filter that only allows tenor GIF links in a specific channel, deleting other image links.

### UniMod
AI-powered auto-moderation using sentiment analysis and AI detection to alert moderators of potential violations.

### VerifyUser
Allows authorized users to verify other members by granting them a specific verification role.

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
