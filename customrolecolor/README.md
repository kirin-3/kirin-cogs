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
- **Holographic**: Apply the holographic role preset.
  - Usage: `[p]myrolecolor holographic`

#### `[p]myrolename <name>`
Change the name of your assigned role.
- **Usage**: `[p]myrolename My New Role Name`

#### `[p]myroleicon [emoji]`
Change the icon of your assigned role.
- **Unicode Emoji**: `[p]myroleicon 👑`
- **Custom Image**: Upload an image (PNG/JPG < 256KB) and run `[p]myroleicon`.

#### `[p]myrolementionable <state>`
Toggle whether your role can be mentioned by others.
- **Usage**: `[p]myrolementionable on` or `[p]myrolementionable off`

#### `[p]colorpreview <hex>`
Generate a preview image of a specific color to see how it looks.
- **Usage**: `[p]colorpreview #00FF00`

#### `[p]colorpalette`
View a generated image of common colors and a copyable text list of hex codes.
- **Usage**: `[p]colorpalette`

## Requirements
- The bot must have `Manage Roles` permission.
- The bot's top role must be higher than the role being managed.
