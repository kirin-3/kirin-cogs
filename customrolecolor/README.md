# Custom Role Color

This cog allows server administrators to assign a specific role to a user, giving them the ability to manage that role's color, name, icon, and mentionable status.

## Commands

### Admin Commands

#### `[p]assignrole <user> <role>`
Assigns a role to a user for management.
- **Usage**: `[p]assignrole @User @Role`
- **Permission**: Manage Roles

---

### User Commands

#### `[p]myrolecolor <color> [secondary_color]`
Change the color of your assigned role. Supports flat colors, gradients, and a holographic preset.

- **Flat Color**: Set a single color.
  - Usage: `[p]myrolecolor #FF0000`
- **Gradient**: Set a gradient between two colors.
  - Usage: `[p]myrolecolor #FF0000 #0000FF`
- **Holographic**: Apply the holographic role preset (uses advanced tertiary coloring).
  - Usage: `[p]myrolecolor holographic`
- **Cooldown**: 10 seconds per use

#### `[p]myrolename <name>`
Change the name of your assigned role.
- **Usage**: `[p]myrolename My New Role Name`
- **Name Length**: 1-100 characters
- **Cooldown**: 10 seconds per use

#### `[p]myroleicon [emoji]`
Change the icon of your assigned role.
- **Unicode Emoji**: `[p]myroleicon 👑`
- **Custom Image**: Upload an image (PNG/JPG < 256KB) and run `[p]myroleicon`.
- **Requirements**: Server must have the ROLE_ICONS feature (Level 2 Boost required)
- **Cooldown**: 10 seconds per use

#### `[p]myrolementionable <state>`
Toggle whether your role can be mentioned by others.
- **Usage**: `[p]myrolementionable on`, `[p]myrolementionable off`, `[p]myrolementionable yes`, `[p]myrolementionable no`, `[p]myrolementionable true`, `[p]myrolementionable false`
- **Cooldown**: 10 seconds per use

#### `[p]colorpreview <hex>`
Generate a preview image of a specific color to see how it looks.
- **Usage**: `[p]colorpreview #00FF00`

#### `[p]colorpalette`
View a generated image of common colors and a copyable text list of hex codes.
- **Usage**: `[p]colorpalette`

## Features
- **Role Management**: Assign roles for individual customization by users
- **Color Options**: Flat colors, gradients, and holographic presets
- **Icon Support**: Unicode emojis and custom images (when server supports ROLE_ICONS feature)
- **Mention Control**: Toggle mentionability of roles
- **Cooldown System**: Prevents spam with 10-second cooldown on user commands
- **Color Utilities**: Preview colors and view color palettes
- **Server Boost Required**: Role icons require Level 2 server boost or higher

## Requirements
- The bot must have `Manage Roles` permission.
- The bot's top role must be higher than the role being managed.
- Server must have Level 2 boost for role icons feature.
