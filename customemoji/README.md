# CustomEmoji

Allows users with a specific role to create and manage their own custom emojis on the server.

## Features
- **User-Managed Emojis**: Create, delete, and rename your own emojis.
- **Slot System**: Limits how many emojis each user can own (default 2).
- **Flexible**: Upload images or copy existing emojis from other servers.
- **Permission-based management**: A Red bot moderator can delete any emoji and view others' emoji lists. A guild member with only the Manage Emojis permission can likewise delete any emoji, but cannot view others' lists.
- **Image validation**: Checks that the image really is a PNG, JPEG or GIF, by its content, and its size (max 256KB) to comply with Discord limits. Downloads from Discord image links or emojis stop as soon as they pass 256KB.
- **Auto-cleanup**: When an emoji is deleted outside the bot (e.g. in Server Settings), its record is dropped right away and the owner's slot is freed.
- **Cooldown**: Creating, renaming and deleting share one 10-second cooldown per member, counted across the commands and the member site.
- **Member site**: Supporters can also list, upload, rename and delete their emojis on `my.unicornia.net` (see the Dashboard cog), under the same rules.

## Commands

### Configuration (Bot Owner Only)
- `[p]ce setrole <role>`: Set the role required to create and rename emojis. Leave empty to remove restriction.
- `[p]ce limit <user> <limit>`: Set a custom emoji limit for a user.
- `[p]ce resetlimit <user>`: Reset a user's limit to the default (2).

### User Commands
- `[p]ce create <name> [emoji_or_url]`: Create a new emoji. You can attach an image or provide an existing emoji or a Discord image link (`cdn.discordapp.com` / `media.discordapp.net`; other hosts are refused).
  - With attachment: `[p]ce create my_emoji` (attach image)
  - With existing emoji: `[p]ce create my_emoji 😄`
  - With URL: `[p]ce create my_emoji https://cdn.discordapp.com/attachments/.../image.png`
- `[p]ce delete <emoji>`: Delete one of your emojis.
- `[p]ce rename <emoji> <new_name>`: Rename one of your emojis. Needs the same role as creating one. Names are 2 to 32 letters, digits and underscores.
- `[p]ce list [user]`: List emojis owned by you or another user.
  - `[p]ce list` - Show your own emojis
  - `[p]ce list @User` - Show another user's emojis (requires Bot Moderator permissions)

## Requirements
- The bot needs `Manage Emojis` permission in the server.
- Users need the configured role to create or rename emojis (if set). Anyone can delete their own.
- Deleting someone else's emoji requires Manage Emojis **or** Red bot moderator permissions; viewing another user's list requires Red bot moderator permissions only.
