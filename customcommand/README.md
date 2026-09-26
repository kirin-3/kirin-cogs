# CustomCommand

Allows users with a specific role to create custom commands.

## Commands

### `[p]customcommand create <trigger> [response]`
Create a custom command.
- **Trigger**: The phrase that triggers the command.
- **Response**: The text the bot will reply with, at most 2,000 characters (one Discord message). Optional if an image is attached. Responses cannot start with `.`, `-`, or `&` (rejected to prevent conflicts with other bots' triggers).
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
- **Dynamic Limits**: Admins can assign different command limits to specific users. The default limit is **1** command per user; the bot owner is exempt from limits.
- **Multi-word Triggers**: Supports triggers with spaces (e.g., "hello world").
- **Image Support**: Attach an image to the `create` command to have it sent as part of the response. Files are stored in the cog's data folder and removed when the command is deleted.
- **Older commands**: Commands created before files were saved keep the attachment link in their response text; that link stops working if the original message is deleted, so recreate those commands. Responses saved before the 2,000-character limit are sent in several messages.
- **Logging**: Logs command creations and deletions to a hardcoded audit-log channel (set in the cog's code).
- **Moderation**: Moderators can delete any custom command.
- **Cooldown**: Creating has a 5-second cooldown per member, counted across the command and the member site.
- **Member site**: Supporters can also list, create and delete their commands on `my.unicornia.net` (see the Dashboard cog), under the same rules. They can also edit a command there: change its trigger, response or file in one step, as if it were deleted and re-created, so the create rules and cooldown apply. Only the active supporter role can create or edit; anyone can delete their own. Changes made there are marked as made on the web in the audit log.
- **Permission-based listing**: Regular users see only their commands, moderators see all commands.

## Requirements
- Users must have the specific supporter role to create commands. The role is hardcoded in the cog's code (like the audit-log channel); there is no command to change it.
- Moderators need Ban Members permission to delete others' commands or see all commands in list.
