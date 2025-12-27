# CustomCommand

Allows users with a specific role to create custom commands.

## Commands

### `[p]customcommand create <trigger> <response>`
Create a custom command.
- **Trigger**: The phrase that triggers the command.
- **Response**: The text the bot will reply with.
- **Note**: To use multi-word triggers or responses, wrap them in quotes.
- **Example**: `[p]cc create "hello world" "Hello there!"`
- **Aliases**: `[p]cc create`

### `[p]customcommand delete [trigger]`
Delete your custom command.
- If you have multiple commands, you must specify the trigger.
- **Example**: `[p]cc delete "hello world"`
- **Aliases**: `[p]cc delete`

### `[p]customcommand limit <user> <limit>`
(Admin only) Set the custom command limit for a specific user.
- **Example**: `[p]cc limit @User 5`

## Features
- **Dynamic Limits**: Admins can assign different command limits to specific users.
- **Multi-word Triggers**: Supports triggers with spaces (e.g., "hello world").
- **Cooldowns**: Commands have a cooldown to prevent spam.

## Requirements
- Users must have the specific supporter role to create commands.
