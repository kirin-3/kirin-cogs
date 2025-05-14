# Patron Cog

A Red Discord Bot cog that integrates with Patreon's API to automatically award users based on their donation amounts.

## Features

- Connect to Patreon's API to fetch donation data
- Automatically send award messages for both new patrons and monthly recurring donations
- Configurable message format (default: `.award {amount} @discordusername`)
- Maps Patreon accounts to Discord users either automatically or manually
- Token refresh mechanism for continuous API access
- Periodic checking for new donations

## Setup

### Prerequisites

1. You need to have a Patreon creator account
2. Register a client application at https://www.patreon.com/portal/registration/register-clients
3. Set up OAuth permissions for the campaign data
4. Get your Client ID, Client Secret, Creator Access Token, and Creator Refresh Token

### Commands

All commands require bot owner permissions to use:

- `[p]patreonset clientid <client_id>` - Set your Patreon API Client ID (DM only)
- `[p]patreonset clientsecret <client_secret>` - Set your Patreon API Client Secret (DM only)
- `[p]patreonset accesstoken <access_token>` - Set your Patreon Creator Access Token (DM only)
- `[p]patreonset refreshtoken <refresh_token>` - Set your Patreon Creator Refresh Token (DM only)
- `[p]patreonset campaignid <campaign_id>` - Set your Patreon Campaign ID
- `[p]patreonset awardchannel <channel>` - Set the channel where award messages will be sent
- `[p]patreonset messageformat <format>` - Set the format for award messages
- `[p]patreonset minamount <amount>` - Set the minimum donation amount that triggers an award
- `[p]patreonset monthly <True/False>` - Enable/disable processing of monthly recurring donations
- `[p]patreonset status` - Show current Patreon API configuration status
- `[p]patreonset checkconnections` - Check Patreon-Discord connections in the system
- `[p]patreonset manualconnect <patreon_id> <discord_user>` - Manually connect a Patreon user to a Discord user
- `[p]patreonset checkpatrons` - Manually trigger a check for new patrons
- `[p]patreonset refreshpatreontoken` - Manually refresh your Patreon access token
- `[p]patreonset cleartransactions` - Clear all processed donation records to reprocess them
- `[p]patreonset listpatrons` - List Discord usernames of current patrons without pinging them
- `[p]patreonset resetapi` - Reset all Patreon API credentials (DM only)
- `[p]patreonset tokenguide` - Provides a step-by-step guide for getting new Patreon API tokens

## Message Format

You can customize the award message format using the following placeholders:
- `{amount}` - The calculated award amount (3000 per 1 EUR/USD donated)
- `{discord_user}` - The Discord user mention
- `{patron_name}` - The patron's full name from Patreon
- `{recurring}` - Will be "new" for first-time donations or "monthly" for recurring donations

Default format: `.award {amount} {discord_user}`

### Amount Calculation

The `{amount}` value is automatically calculated based on the donation amount:
- For each 1 EUR/USD donated, the base amount will be 3000
- Bonus percentages are applied based on donation tiers:
  - 5-9.99 EUR: 5% bonus
  - 10-19.99 EUR: 10% bonus
  - 20-39.99 EUR: 15% bonus
  - 40+ EUR: 20% bonus

Examples:
- A 2 EUR donation: 2 × 3000 = 6000 (no bonus)
- A 5 EUR donation: 5 × 3000 × 1.05 = 15750
- A 10 EUR donation: 10 × 3000 × 1.10 = 33000
- A 20 EUR donation: 20 × 3000 × 1.15 = 69000
- A 40 EUR donation: 40 × 3000 × 1.20 = 144000

## How It Works

1. The cog connects to the Patreon API using your creator credentials
2. It fetches members (patrons) data from your campaign
3. For each patron, it checks:
   - If they are a new patron (first-time donation)
   - If they have a recurring monthly donation that hasn't been processed
4. If a Discord connection is found, it sends an award message to the configured channel
5. The cog keeps track of processed donations by storing the last charge date for each patron

## Monthly Processing

By default, the cog will send award messages for both:
- New patrons joining for the first time
- Existing patrons when their monthly donation renews

You can disable the monthly processing using the `[p]patreonset monthly False` command if you only want messages for new patrons.

## Discord Connection Methods

Discord users can be connected to Patreon accounts in two ways:
1. **Automatic** - If the patron has connected their Discord account to Patreon
2. **Manual** - Using the `[p]patreonset manualconnect` command

## Installation

```
[p]repo add kirin-cogs https://github.com/your-username/kirin-cogs
[p]cog install kirin-cogs patron
[p]load patron
```

## Notes

- The cog checks for new patrons every hour
- Only the bot owner can configure and use the cog commands
- Sensitive API credentials can be set via DM for increased security
- Make sure your Discord bot has permission to send messages in the award channel
- Patron data is stored securely and only used for the award process

## Troubleshooting

### Token Expiration Issues

If you see errors like `Error fetching patrons: Failed to refresh token: HTTP 401 - {"error":"invalid_grant"}`, your Patreon refresh token has expired or been revoked. Patreon tokens can expire after a period of inactivity or if permissions are changed.

To fix this:
1. Use `[p]patreonset resetapi confirm=True` to reset all credentials (DM only)
2. Use `[p]patreonset tokenguide` to get detailed instructions for generating new tokens
3. Follow the guide to obtain fresh tokens from Patreon's OAuth system
4. Set the new tokens using the appropriate commands

### Manual Token Refresh

If token refresh fails automatically, you can try manually refreshing the token:
1. Use `[p]patreonset refreshpatreontoken` to attempt a manual refresh
2. If this fails, you'll need to get a new token from Patreon 