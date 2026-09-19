# AntiNuke Cog

A server protection system for Red-DiscordBot, inspired by WickBot's AntiNuke feature. This cog monitors your server for potentially destructive actions and automatically quarantines users who exceed configured thresholds.

All commands are prefix-only (no slash commands).

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Commands Reference](#commands-reference)
- [Trust System](#trust-system)
- [Quarantine System](#quarantine-system)
- [Monitored Actions](#monitored-actions)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

## Features

### Core Protection
- **Channel Monitoring**: Tracks channel creation and deletion
- **Role Monitoring**: Tracks role creation and deletion, plus grants of dangerous permissions
- **Ban/Kick Monitoring**: Monitors member bans and kicks
- **Webhook Monitoring**: Tracks webhook creation and deletion
- **Guild Prune Detection**: Instantly quarantines anyone who starts a member prune
- **Vanity URL Protection**: Monitors vanity URL changes
- **Bot Add Detection**: Detects newly added bots and can auto-kick unauthorized ones

### Advanced Features
- **RAM-Based Action Tracking**: High-performance in-memory action counting with automatic cleanup
- **Hybrid Event Detection**: Combines Gateway events (instant detection) with Audit Log lookups (actor identification)
- **Per-Action Thresholds and Timeframes**: Each action type has its own threshold and time window
- **Atomic Quarantine**: Single API call replaces all roles with the quarantine role
- **Role Restoration**: Full role snapshot is retained and restored when the user is unquarantined
- **Bot Kick**: Optionally auto-kicks bot accounts added to the server
- **Trust System**: Whitelist users and roles to bypass monitoring
- **Logging Channel**: Dedicated channel for all AntiNuke alerts, with owner DMs as fallback

Quarantine is the only enforcement action. Bots that trigger protection are quarantined too; enabling bot kick additionally kicks newly added unauthorized bots.

## Installation

### Requirements
- Red-DiscordBot 3.5.0 or higher
- Python 3.11+
- Bot must have the following permissions:
  - `manage_roles` - For quarantine role management
  - `view_audit_log` - For actor identification
  - `kick_members` - For auto-kicking unauthorized bots (optional)
  - Send/Embed permissions in the configured log channel

### Install Steps

1. **Add the cog to your RedBot**:
   ```bash
   [p]repo add kirin-cogs https://github.com/kirin-3/kirin-cogs
   [p]cog install kirin-cogs antinuke
   ```

2. **Load the cog**:
   ```bash
   [p]load antinuke
   ```

## Quick Start

### Basic Setup in 3 Steps

1. **Set the log channel**:
   ```bash
   [p]antinuke logchannel #anti-nuke-logs
   ```

2. **Set the Quarantine Role**:
   ```bash
   [p]antinuke quarantinerole @Quarantined
   ```

   If the role doesn't exist, create one with these recommended settings:
   - No permissions (or very limited)
   - Positioned below the bot's role
   - Different color for visibility

3. **Enable AntiNuke**:
   ```bash
   [p]antinuke enable
   ```

> The `[p]antinuke disable` command and trust management commands are restricted to the **guild owner**.

### Default Thresholds

Out of the box, every action type is monitored with these defaults:

| Action Types | Threshold | Timeframe |
|---|---|---|
| `channel_create`, `channel_delete`, `role_create`, `role_delete` | 3 | 60 seconds |
| `ban`, `kick` | 3 | 120 seconds |
| `webhook_create`, `webhook_delete` | 2 | 60 seconds |
| `dangerous_permission_add`, `vanity_change`, `bot_add` | 1 | 60 seconds |
| `guild_prune` | 0 (instant) | 60 seconds |

## How It Works

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Discord Gateway Events                      │
│      (on_guild_channel_delete, on_member_ban, audit logs)        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Event Handlers                             │
│  • Instant event detection                                       │
│  • Audit Log lookup for actor identification                     │
│  • Trust bypass check                                            │
│  • Action cache increment                                        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Action Cache (RAM)                          │
│  • Per-user, per-action-type timestamp tracking                  │
│  • Automatic cleanup of expired entries                          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Threshold Check & Quarantine                   │
│  • Compare action count against configured threshold             │
│  • Atomic role replacement with quarantine role                  │
│  • Role snapshot saved for restoration                           │
│  • Log channel notification (+ owner DM fallback)                │
│  • Bot kick for unauthorized bots (if enabled)                   │
└─────────────────────────────────────────────────────────────────┘
```

### Event Detection Flow

1. **Gateway Event Received**: Discord sends an event (e.g., channel deleted)
2. **Audit Log Lookup**: Bot fetches audit logs to identify who performed the action
3. **Trust Check**: If the actor is trusted (owner or whitelisted), skip
4. **Action Recording**: Increment the action counter for this user
5. **Threshold Check**: If count exceeds the threshold within the timeframe, trigger quarantine
6. **Quarantine Execution**: Roles are replaced with the quarantine role; snapshot is saved
7. **Logging**: Send detailed alert to the configured log channel

### Time Window System

Each action type has its own timeframe (default: 60 seconds, or 120 seconds for bans/kicks; minimum 10 seconds). A threshold of `0` means instant quarantine on the first action.

- If a user deletes 3 channels within 60 seconds, they trigger the threshold
- If they delete 1 channel, wait 61 seconds, then delete 2 more, they don't trigger
- The counter resets automatically as time passes

## Commands Reference

All commands are under the `[p]antinuke` group (alias: `[p]an`). The group requires **Administrator** or **Manage Server** permission and only works in servers.

### Configuration Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke enable` | Enable AntiNuke for this server |
| `[p]antinuke disable` | Disable AntiNuke (guild owner only) |
| `[p]antinuke logchannel <channel>` | Set the log channel for AntiNuke alerts |
| `[p]antinuke quarantinerole <role>` | Set the quarantine role (must be below the bot's top role) |
| `[p]antinuke settings` (alias `show`) | Show current AntiNuke settings |

### Monitoring Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke monitor` (alias `mon`) | Show monitoring configuration for all action types |
| `[p]antinuke monitor enable <action_type>` | Enable monitoring for an action type |
| `[p]antinuke monitor disable <action_type>` | Disable monitoring for an action type |
| `[p]antinuke monitor threshold <action_type> <threshold> [timeframe]` | Set threshold and timeframe (default 60s, min 10s; threshold 0 = instant) |
| `[p]antinuke monitor botkick <enabled>` | Toggle auto-kicking of newly added unauthorized bots |

### Trust Management Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke trust` (alias `trusted`) | Manage trusted users and roles |
| `[p]antinuke trust adduser <user>` | Add a user to the trust list (bots rejected) |
| `[p]antinuke trust removeuser <user>` | Remove a user from the trust list |
| `[p]antinuke trust addrole <role>` | Add a role to the trust list |
| `[p]antinuke trust removerole <role>` | Remove a role from the trust list |
| `[p]antinuke trust list` (alias `show`) | Show all trusted users and roles |
| `[p]antinuke trust clear` | Clear all trusted users and roles |

> `adduser`, `removeuser`, `addrole`, `removerole`, and `clear` are restricted to the **guild owner**.

### Quarantine Management Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke quarantine` (alias `q`) | Manage quarantined users |
| `[p]antinuke quarantine list` (alias `show`) | Show all currently quarantined users |
| `[p]antinuke quarantine restore <user>` (aliases `unquarantine`, `unq`) | Restore a quarantined user's roles |
| `[p]antinuke quarantine force <user> [reason]` | Forcibly quarantine a user |
| `[p]antinuke quarantine clear <user>` | Clear a user's quarantine record without restoring roles |
| `[p]antinuke quarantine info <user>` | Show detailed quarantine information for a user |
| `[p]antinuke quarantine cleanup` | Clean up quarantine records for users who left the server |

## Trust System

The trust system allows you to whitelist certain users and roles that will bypass all AntiNuke monitoring.

### Who is Automatically Trusted?

- **Server Owner**: Always trusted, cannot be removed

### Adding Trusted Users

```bash
# Trust a specific user (guild owner only)
[p]antinuke trust adduser @AdminUser

# Trust all members with a specific role (guild owner only)
[p]antinuke trust addrole @Administrators
```

### Best Practices for Trust

1. **Limit Trusted Roles**: Only trust roles that require dangerous permissions
2. **Regular Audits**: Periodically review the trust list with `[p]antinuke trust list`
3. **Role Hierarchy**: Ensure trusted roles are high in the hierarchy
4. **Documentation**: Keep track of why each user/role is trusted

**Not Recommended to Trust:**
- Regular member roles
- Trial moderator roles
- Any role with frequent member turnover

## Quarantine System

### How Quarantine Works

When a user triggers AntiNuke:

1. **Role Snapshot**: All of the user's current roles are saved to Config
2. **Atomic Strip**: The user's roles are replaced with only the quarantine role in a single API call
3. **Notification**: Alert is sent to the log channel (and the owner by DM if no log channel is set)
4. **Bot Handling**: If the offender is a bot, it is quarantined as well

Quarantine operations are serialized per user and tracked with a pending/completed/failed state, so failed operations stay retryable.

### Quarantine Role Requirements

The quarantine role should have:
- ❌ No dangerous permissions
- ❌ Cannot mention @everyone or @here
- ❌ Cannot send messages in most channels
- ✅ Position below the bot's highest role
- ✅ Distinctive color for visibility

### Restoring Users

When you unquarantine a user:

```bash
[p]antinuke quarantine restore @UserName
```

This will:
1. Restore the previously saved roles
2. Remove the quarantine role
3. Log the restoration

## Monitored Actions

| Action Type | Description | Default Threshold / Timeframe |
|-------------|-------------|-------------------------------|
| `channel_create` | Channels created | 3 / 60s |
| `channel_delete` | Channels deleted | 3 / 60s |
| `role_create` | Roles created | 3 / 60s |
| `role_delete` | Roles deleted | 3 / 60s |
| `ban` | Members banned | 3 / 120s |
| `kick` | Members kicked | 3 / 120s |
| `webhook_create` | Webhooks created | 2 / 60s |
| `webhook_delete` | Webhooks deleted | 2 / 60s |
| `guild_prune` | Member prune started (instant) | 0 / 60s |
| `dangerous_permission_add` | Dangerous permission granted to a role | 1 / 60s |
| `vanity_change` | Vanity URL changed | 1 / 60s |
| `bot_add` | Bot added to the server | 1 / 60s |

**Special: Dangerous Permission Detection**

The `dangerous_permission_add` action triggers when any of these permissions is granted to a role:

- `administrator`
- `manage_guild`
- `manage_roles`
- `manage_channels`
- `manage_webhooks`
- `ban_members`
- `kick_members`
- `manage_nicknames`
- `mention_everyone`
- `view_audit_log`

**Note**: Vanity URL changes are detected via the `on_guild_update` event. This is highly sensitive as vanity URL theft is a common attack vector.

## Best Practices

### 1. Start with Defaults

The default thresholds are a solid starting point. Lower the threshold (or set it to `0` for instant) on the actions you consider most dangerous:

```bash
[p]antinuke monitor threshold role_delete 2
[p]antinuke monitor threshold vanity_change 0 10
```

### 2. Layer Your Protection

Combine AntiNuke with other security measures:
- Verification levels (Settings → Safety Setup)
- Role hierarchy management
- 2FA requirement for moderators
- Audit log monitoring

### 3. Regular Reviews

Monthly tasks:
- Review the trust list: `[p]antinuke trust list`
- Check quarantine records: `[p]antinuke quarantine list`
- Adjust thresholds based on activity: `[p]antinuke monitor`
- Verify log channel is accessible

### 4. Test Your Setup

After configuration, test with a trusted user:
1. Have them perform actions near the threshold
2. Verify alerts appear in the log channel
3. Confirm quarantine works correctly
4. Test role restoration

### 5. Emergency Procedures

Prepare for false positives:
1. Know how to quickly unquarantine users: `[p]antinuke quarantine restore`
2. Have a backup communication channel
3. Document `[p]antinuke disable` for emergencies (guild owner only)

### 6. Role Hierarchy

Ensure proper hierarchy:
```
Bot Role (Highest)
    ↓
Administrator Roles
    ↓
Moderator Roles
    ↓
Trusted Member Roles
    ↓
Regular Member Roles
    ↓
Quarantine Role (Lowest, above @everyone)
```

## Troubleshooting

### AntiNuke Not Triggering

**Symptoms**: Users perform actions but aren't quarantined

**Checks**:
1. Is AntiNuke enabled? `[p]antinuke settings`
2. Is monitoring enabled for the action? `[p]antinuke monitor`
3. Is the quarantine role set? `[p]antinuke settings`
4. Is the user trusted? `[p]antinuke trust list`
5. Are thresholds too high? `[p]antinuke monitor`
6. Does the bot have required permissions?

### False Positives

**Symptoms**: Legitimate actions trigger quarantine

**Solutions**:
1. Increase thresholds/timeframes: `[p]antinuke monitor threshold <action> <count> <seconds>`
2. Trust the user/role: `[p]antinuke trust adduser @User` (guild owner only)
3. Disable monitoring for that action: `[p]antinuke monitor disable <action>`

### Audit Log Not Working

**Symptoms**: Actions detected but actor not identified

**Checks**:
1. Does bot have `view_audit_log` permission?
2. Is the bot's role high enough in hierarchy?
3. Are audit logs enabled in server settings?

### Quarantine Role Not Applied

**Symptoms**: User triggered but roles not stripped

**Checks**:
1. Is quarantine role set? `[p]antinuke settings`
2. Is bot's role above the user's highest role?
3. Does bot have `manage_roles` permission?
4. Is the quarantine role below bot's role?
5. Check `[p]antinuke quarantine info <user>` for the recorded error state

### Log Channel Not Receiving Messages

**Symptoms**: No alerts in log channel

**Checks**:
1. Is log channel set? `[p]antinuke settings`
2. Can bot send messages in that channel?
3. Can bot embed links in that channel?
4. Without a log channel, alerts are DMed to the server owner

## FAQ

### General Questions

**Q: Does AntiNuke protect against the server owner?**  
A: No, the server owner is always trusted and cannot be monitored. This is by design.

**Q: Can I exclude specific channels from monitoring?**  
A: Currently, no. All channels are monitored equally.

**Q: What happens if the bot goes offline?**  
A: Actions during downtime are not monitored. Consider having backup security measures.

**Q: Can I see who almost triggered a threshold?**  
A: Currently, only triggered events are logged. Partial counts are not persisted.

### Configuration Questions

**Q: Can violators be kicked or banned instead of quarantined?**  
A: No. Quarantine is the only enforcement action; it strips roles so you can review. Enable `[p]antinuke monitor botkick on` to auto-kick newly added unauthorized bots.

**Q: Should I enable bot kicking?**  
A: Yes, unless you have bots that legitimately perform administrative actions. Rogue bots are a common attack vector.

**Q: What timeframes should I use?**  
A: The defaults (60s, 120s for bans/kicks) suit most servers. Shorter windows catch burst attacks but risk false positives during bulk moderation.

### Trust System Questions

**Q: Can I trust everyone with a specific permission?**  
A: No, you must trust by user or role. Consider creating a "Trusted Admin" role.

**Q: What if a trusted account is compromised?**  
A: Remove them from trust immediately. The server owner can always override.

**Q: Do trusted users' actions get logged?**  
A: No, trusted users' actions bypass the system entirely and are not logged.

### Quarantine Questions

**Q: Can I customize the quarantine message?**  
A: Currently, no. The log message format is standardized.

**Q: What if someone needs to be permanently quarantined?**  
A: Use Discord's built-in timeout or ban features for permanent restrictions.

**Q: Can quarantined users see channels?**  
A: That depends on your channel permissions. Configure the quarantine role's permissions accordingly.

### Technical Questions

**Q: What happens to data if I reload the cog?**  
A: Configuration and quarantine records are persisted. In-memory action counts are reset (intentional behavior).

**Q: Can I export/import configuration?**  
A: Use `[p]antinuke settings` to view configuration. Direct export/import is not currently available.

---

## Support

For issues, feature requests, or contributions:
- Open an issue on the repository
- Contact the cog author

## License

This cog is provided under the same license as the kirin-cogs repository.

## Credits

- Inspired by WickBot's AntiNuke system
- Built for Red-DiscordBot
- Uses Discord.py's event system and audit log API

## Recovery and retention

Quarantine changes are serialized per guild/member. The first role snapshot is retained until Discord confirms the edit, and failed operations remain retryable. Unloading the cog cancels and inspects investigator/quarantine tasks. Trusted IDs and quarantine snapshots are removed through Red's user-data deletion hook.
