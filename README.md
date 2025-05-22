# Kirin's Red Discord Bot Cogs

A collection of custom cogs for [Red Discord Bot](https://github.com/Cog-Creators/Red-DiscordBot).

## Available Cogs

### CustomRoleColor
Allows administrators to assign a role to a user and lets that user customize the color, name, and icon of their assigned role.

**Commands:**
- `[p]assignrole <user> <role>` - Assigns a role to a user for customization
- `[p]myrolecolor <hex_color>` - Changes the color of your assigned role
- `[p]myrolename <new_name>` - Changes the name of your assigned role
- `[p]myroleicon <emoji>` - Changes the icon of your assigned role
- `[p]myrolementionable <on/off>` - Toggles whether your assigned role is mentionable

### TabooAccess
Provides a button-based interface for users to gain or remove access to specific content channels.

**Commands:**
- `[p]sendtaboo` - Sends the taboo access control buttons

### UnicornSecurity
Contains moderation tools including a filter that only allows tenor GIF links in specific channels.

**Commands:**
- `[p]imagefilter status` - Shows the current status of the image filter
- `[p]imagefilter setchannel [channel]` - Sets the channel for the Tenor-only filter

## Installation

To install these cogs, run the following commands in Discord:

```
[p]repo add kirin-cogs https://github.com/your-username/kirin-cogs
[p]cog install kirin-cogs <cogname>
[p]load <cogname>
```

Replace `<cogname>` with the name of the cog you want to install.

## Requirements

- Red Discord Bot V3
- discord.py 2.0+

## License

All cogs are released under the MIT License.