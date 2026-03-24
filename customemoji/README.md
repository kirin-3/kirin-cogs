# CustomEmoji

Allows users with a specific role to create and manage their own custom emojis on the server.

## Features
- **User-Managed Emojis**: Create, delete, and rename your own emojis.
- **Slot System**: Limits how many emojis each user can own (default 2).
- **Flexible**: Upload images or copy existing emojis from other servers.

## Commands

### Configuration (Bot Owner Only)
- `[p]ce setrole <role>`: Set the role required to create emojis. Leave empty to remove restriction.
- `[p]ce limit <user> <limit>`: Set a custom emoji limit for a user.
- `[p]ce resetlimit <user>`: Reset a user's limit to the default (2).

### User Commands
- `[p]ce create <name> [emoji_or_url]`: Create a new emoji. You can attach an image or provide an existing emoji/URL.
  - With attachment: `[p]ce create my_emoji` (attach image)
  - With existing emoji: `[p]ce create my_emoji 😄`
  - With URL: `[p]ce create my_emoji https://example.com/image.png`
- `[p]ce delete <emoji>`: Delete one of your emojis.
- `[p]ce rename <emoji> <new_name>`: Rename one of your emojis.
- `[p]ce list [user]`: List emojis owned by you or another user.
  - `[p]ce list` - Show your own emojis
  - `[p]ce list @User` - Show another user's emojis (requires moderator permissions)

## Features
- **User-Managed Emojis**: Create, delete, and rename your own emojis.
- **Slot System**: Limits how many emojis each user can own (default 2).
- **Flexible**: Upload images or copy existing emojis from other servers.
- **Permission-based management**: Moderators can delete any emoji and view others' emoji lists.
- **Image validation**: Checks image type and size (max 256KB) to comply with Discord limits.
- **Auto-cleanup**: Automatically removes records of emojis that were deleted outside the bot's control.
- **Cooldowns**: Commands have cooldowns to prevent spam.

## Requirements
- The bot needs `Manage Emojis` permission in the server.
- Users need the configured role to create emojis (if set).
- Moderators need Manage Emojis or Bot Moderator permissions to manage others' emojis.
