# CustomCommand

Allows users with a specific role to create custom commands.

## Commands

### `[p]customcommand create <trigger> [response]`
Create a custom command.
- **Trigger**: The phrase that triggers the command.
- **Response**: The text the bot will reply with, at most 2,000 characters (one Discord message). Optional if an image is attached.
- **Attachments**: You can attach a file (up to 8 MB) to this command to have it sent with the response. The bot saves the file itself, so the command keeps working after the original message is deleted.
- **Note**: To use multi-word triggers or responses, wrap them in quotes.
- **Example**: `[p]cc create "hello world" "Hello there!"`
- **Aliases**: `[p]cc create`

### `[p]customcommand delete [trigger]`
Delete your custom command.
- If you have multiple commands, you must specify the trigger.
- **Moderators**: Users with Ban Members permission can delete any custom command by specifying the trigger.
- **Example**: `[p]cc delete "hello world"`
- **Aliases**: `[p]cc delete`

### `[p]customcommand limit <user> <limit>`
(Admin only) Set the custom command limit for a specific user.
- **Example**: `[p]cc limit @User 5`

### `[p]customcommand list`
List custom commands.
- **Regular users**: See only your own commands.
- **Moderators** (users with Ban Members permission): See all commands and their owners.
- **Example**: `[p]cc list`

## Features
- **Dynamic Limits**: Admins can assign different command limits to specific users.
- **Multi-word Triggers**: Supports triggers with spaces (e.g., "hello world").
- **Image Support**: Attach an image to the `create` command to have it sent as part of the response. Files are stored in the cog's data folder and removed when the command is deleted.
- **Older commands**: Commands created before files were saved keep the attachment link in their response text; that link stops working if the original message is deleted, so recreate those commands. Responses saved before the 2,000-character limit are sent in several messages.
- **Logging**: Logs command creations and deletions to a hardcoded audit-log channel (set in the cog's code).
- **Moderation**: Moderators can delete any custom command.
- **Cooldowns**: Commands have a cooldown to prevent spam.
- **Permission-based listing**: Regular users see only their commands, moderators see all commands.

## Requirements
- Users must have the specific supporter role to create commands.
- Moderators need Ban Members permission to delete others' commands or see all commands in list.
