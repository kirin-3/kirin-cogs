# Honeypot

Honeypot is an immediate tripwire for compromised or hostile accounts in Unicornia. It is intentionally hardcoded and
inactive outside the configured guild and channel.

When a non-exempt member posts in the honeypot channel, the cog captures the message text and attachment filenames,
deletes the message, and chooses an action from the member's server tenure:

- Members who joined less than 3 days ago receive an appeal notice and are permanently banned. One day of their message
  history is purged. A failed DM does not prevent the ban.
- Members with at least 3 days of tenure, or an unknown join date, have every assignable role removed and receive a
  28-day timeout in one Discord request. Their removed role IDs are saved before the request so staff can restore them.
  The compromised-account DM is attempted only after quarantine succeeds.

Bots, webhook messages, non-member authors, and members holding the staff role are ignored. A per-member lock prevents a
message burst from running enforcement more than once. Outcomes and failures are sent to the hardcoded log channel.

> [!IMPORTANT]
> Quarantine depends on `@everyone` having no channel visibility in Unicornia. A member with no roles must be unable to
> view or post in ordinary channels. The 28-day timeout is never renewed; the role strip is the lasting containment.

## Hardcoded values

| Setting | Value |
| --- | ---: |
| Guild | `684360255798509578` |
| Honeypot channel | `1542655461738938489` |
| Log channel | `1542663016452063366` |
| Staff role | `696020813299580940` |
| New-member cutoff | 3 days |
| Quarantine timeout | 28 days |
| Ban message purge | 86,400 seconds (1 day) |
| Appeal form | `https://forms.gle/SdrjyV9ggi3hBQbh8` |

There is no enable toggle. Loading the cog arms it immediately.

## Required bot permissions

The bot needs these guild and channel permissions in Unicornia:

- `Ban Members` (`ban_members`)
- `Manage Roles` (`manage_roles`)
- `Moderate Members` (`moderate_members`)
- `Manage Messages` (`manage_messages`)
- Permission to view and send messages in the log channel

The bot's highest role must be above every member and ordinary role it is expected to moderate. Managed roles and roles
above the bot are retained during quarantine because Discord does not allow the bot to remove them.

## Staff commands

The hybrid command group is available to members with staff role `696020813299580940`, Red administrators and bot
owners, or members with `Manage Roles`:

- `[p]honeypot list` lists stored members, record state, quarantine time, and role-snapshot size.
- `[p]honeypot restore <member>` unions the stored roles with the member's current roles and clears the timeout in one
  request. Deleted or newly unassignable roles are skipped and counted. The record is deleted only after success.
- `[p]honeypot clear <member>` deletes the record without changing the member's roles or timeout.

Slash-command equivalents are registered by Red because the command group is hybrid.

## Deployment checklist

Complete every item before loading the cog:

1. Confirm the bot has `ban_members`, `manage_roles`, `moderate_members`, and `manage_messages` in Unicornia.
2. Confirm the bot's highest role is above the members and roles it must moderate.
3. Confirm `@everyone` cannot view ordinary channels. This is required for role stripping to remain effective after the
   fixed timeout expires.
4. Confirm ordinary members can see and post in channel `1542655461738938489`; an unreachable trap catches nothing.
5. Confirm the bot can view and send embeds in log channel `1542663016452063366`.
6. Load the cog only after the checks pass. Use `[p]unload honeypot` to disarm it.

Quarantine records persist across unloads and restarts. Red data-deletion requests remove a user's records from every
guild, which also removes the automatic role-restore path for that user.
