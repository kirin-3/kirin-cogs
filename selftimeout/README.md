# SelfTimeout

Lets members time themselves out for a break.

## Commands

### `[p]break <duration>`
Times you out for `duration`, from 1 minute up to 28 days (Discord's timeout limit). Durations look like `30m`,
`2h`, `3 days` or `1w`; a bare number is minutes. Also available as `/break`.

The bot first asks you to confirm with buttons (an ephemeral message for `/break`). Once you confirm or cancel, or
after 60 seconds, it deletes the confirmation and your command message.

It refuses the server owner and administrators, whom Discord doesn't allow to be timed out, and members whose top role
is at or above the bot's.

## Permissions

The bot needs **Timeout Members**, and **Manage Messages** to delete the prefix command message.
