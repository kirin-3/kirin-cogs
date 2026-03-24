# NitroAward Cog

The NitroAward cog automatically rewards server members with currency when they boost the server. This is designed to work with the Unicornia economy system, awarding 5000 currency units to users who start boosting the server.

## Features

- Automatically detects when a user starts boosting the server
- Awards 5000 currency to the user who boosted
- Prevents duplicate awards for the same boost instance
- Concurrent processing protection to avoid race conditions
- Integration with the Unicornia economy system

## Requirements

- Red-DiscordBot 3.5.0 or higher
- Python 3.11 or higher
- Unicornia cog must be loaded and functioning

## Installation

1. Install the cog using Red's `[p]cog install kirin-cogs nitroaward`
2. Load the cog with `[p]load nitroaward`
3. Make sure the Unicornia cog is also loaded as this cog depends on it for currency operations

## How It Works

Whenever a user starts boosting your server, the NitroAward cog will automatically detect this action and reward the user with 5000 currency units. The system keeps track of the timestamp of each boost to avoid rewarding the same boost instance multiple times.

The system is designed to be robust and handles edge cases like:
- Concurrent boost events for the same user
- Ensuring the user is still boosting when the reward is processed
- Graceful handling when the Unicornia cog isn't available

## Commands

This cog does not provide any user-facing commands. All functionality is automatic and occurs in the background when users boost the server.

## Configuration

There are currently no user-configurable settings for this cog. The currency amount is fixed at 5000 units per boost, and cannot be changed without modifying the code.

## Dependencies

- **Unicornia Cog**: This cog relies on the Unicornia economy system to add currency to users' balances. Without Unicornia loaded and functioning properly, the rewards will not be distributed.

## Notes

- The cog stores a timestamp of the last boost rewarded for each user in the bot's configuration to prevent duplicate rewards
- No personal data is stored beyond the minimum necessary to prevent duplicate rewards
- The system is designed to be efficient and will not award currency if the Unicornia cog is not available

## Support

If you experience issues with this cog, ensure that:
1. Both NitroAward and Unicornia cogs are properly loaded
2. The bot has appropriate permissions to detect server boosts
3. The Unicornia economy system is properly configured and functional