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
- `[p]ce delete <emoji>`: Delete one of your emojis.
- `[p]ce rename <emoji> <new_name>`: Rename one of your emojis.
- `[p]ce list [user]`: List your owned emojis. Mods can view others' lists.

## Requirements
- The bot needs `Manage Emojis` permission in the server.
