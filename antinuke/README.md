# AntiNuke Cog

A comprehensive server protection system for Red-DiscordBot, inspired by WickBot's AntiNuke feature. This cog monitors your server for potentially destructive actions and automatically quarantines users who exceed configured thresholds.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Configuration](#configuration)
- [Commands Reference](#commands-reference)
- [Trust System](#trust-system)
- [Quarantine System](#quarantine-system)
- [Monitored Actions](#monitored-actions)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

## Features

### Core Protection
- **Channel Monitoring**: Tracks creation, deletion, and updates of channels
- **Role Monitoring**: Tracks creation, deletion, and permission changes on roles
- **Ban/Kick Monitoring**: Monitors member bans and kicks
- **Webhook Monitoring**: Tracks webhook creation and deletion
- **Emoji Monitoring**: Tracks emoji creation and deletion
- **Invite Monitoring**: Tracks invite creation and deletion
- **Vanity URL Protection**: Monitors and protects vanity URL changes

### Advanced Features
- **RAM-Based Action Tracking**: High-performance in-memory action counting with automatic cleanup
- **Hybrid Event Detection**: Combines Gateway events (instant detection) with Audit Log lookups (actor identification)
- **Atomic Quarantine**: Single API call to strip all roles and apply quarantine role
- **Non-Blocking Execution**: All quarantine actions run asynchronously without blocking the bot
- **Role Restoration**: Full role backup and restoration when users are unquarantined
- **Bot Detection**: Automatically identifies and can kick bot accounts that trigger protection
- **Configurable Thresholds**: Set custom limits for each action type per time window
- **Trust System**: Whitelist users and roles to bypass monitoring
- **Punishment Tiers**: Choose between quarantine, kick, or ban for violators
- **Logging Channel**: Dedicated channel for all AntiNuke alerts

## Installation

### Requirements
- Red-DiscordBot 3.5.0 or higher
- Discord.py 2.4.0 or higher
- Bot must have the following permissions:
  - `manage_roles` - For quarantine role management
  - `manage_channels` - For channel protection
  - `ban_members` - For ban monitoring and punishment
  - `kick_members` - For kick monitoring and punishment
  - `view_audit_log` - For actor identification
  - `manage_webhooks` - For webhook protection
  - `manage_guild` - For vanity URL protection
  - `manage_emojis` - For emoji protection

### Install Steps

1. **Add the cog to your RedBot**:
   ```bash
   [p]repo add kirin-cogs https://github.com/yourusername/kirin-cogs
   [p]cog install kirin-cogs antinuke
   ```

2. **Load the cog**:
   ```bash
   [p]load antinuke
   ```

3. **Initial Setup**:
   ```bash
   [p]antinuke setup
   ```

## Quick Start

### Basic Setup in 3 Steps

1. **Enable AntiNuke**:
   ```bash
   [p]antinuke toggle on
   ```

2. **Set the Quarantine Role**:
   ```bash
   [p]antinuke quarantine role @Quarantined
   ```
   
   If the role doesn't exist, create one with these recommended settings:
   - No permissions (or very limited)
   - Positioned below the bot's role
   - Different color for visibility

3. **Set the Log Channel**:
   ```bash
   [p]antinuke logchannel #anti-nuke-logs
   ```

### Recommended Initial Thresholds

For most servers, these thresholds provide good protection without false positives:

```bash
[p]antinuke threshold channel_delete 3
[p]antinuke threshold channel_create 5
[p]antinuke threshold role_delete 2
[p]antinuke threshold ban_add 5
[p]antinuke threshold webhook_create 3
```

## How It Works

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Discord Gateway Events                      │
│   (on_guild_channel_delete, on_member_ban, on_guild_role_update) │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Event Handler (events.py)                    │
│  • Instant event detection                                       │
│  • Audit Log lookup for actor identification                     │
│  • Trust bypass check                                            │
│  • Action cache increment                                        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Action Cache (utils.py)                      │
│  • RAM-based action counting                                     │
│  • Per-user, per-action-type tracking                           │
│  • Automatic cleanup of expired entries                         │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Threshold Check (antinuke.py)                  │
│  • Compare action count against configured threshold            │
│  • If exceeded → trigger punishment                             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Quarantine Actions (actions.py)                │
│  • Atomic role strip + quarantine role assignment               │
│  • Role backup for restoration                                  │
│  • Log channel notification                                     │
│  • Bot kick (if configured)                                     │
└─────────────────────────────────────────────────────────────────┘
```

### Event Detection Flow

1. **Gateway Event Received**: Discord sends an event (e.g., channel deleted)
2. **Audit Log Lookup**: Bot fetches audit logs to identify who performed the action
3. **Trust Check**: If the actor is trusted (owner or whitelisted), skip
4. **Action Recording**: Increment the action counter for this user
5. **Threshold Check**: If count exceeds threshold, trigger punishment
6. **Punishment Execution**: Quarantine, kick, or ban the user
7. **Logging**: Send detailed alert to the configured log channel

### Time Window System

Actions are tracked within a configurable time window (default: 10 seconds). This means:
- If a user deletes 3 channels within 10 seconds, they trigger the threshold
- If they delete 1 channel, wait 11 seconds, then delete 2 more, they don't trigger
- The counter resets automatically as time passes

## Configuration

### Core Settings

| Setting | Command | Default | Description |
|---------|---------|---------|-------------|
| Enabled | `[p]antinuke toggle` | `false` | Master toggle for AntiNuke |
| Quarantine Role | `[p]antinuke quarantine role` | `None` | Role applied to quarantined users |
| Log Channel | `[p]antinuke logchannel` | `None` | Channel for AntiNuke alerts |
| Punishment | `[p]antinuke punishment` | `quarantine` | Action taken on violators |
| Time Window | `[p]antinuke timewindow` | `10` | Seconds for threshold counting |

### Threshold Configuration

Each action type has its own threshold. Set them individually:

```bash
[p]antinuke threshold <action_type> <count>
```

#### Available Action Types

| Action Type | Description | Recommended Threshold |
|-------------|-------------|----------------------|
| `channel_create` | Channels created | 5 |
| `channel_delete` | Channels deleted | 2-3 |
| `channel_update` | Channels modified | 5 |
| `role_create` | Roles created | 5 |
| `role_delete` | Roles deleted | 2 |
| `role_update` | Roles modified (esp. dangerous perms) | 3 |
| `ban_add` | Members banned | 3-5 |
| `ban_remove` | Bans removed (unban) | 5 |
| `member_kick` | Members kicked | 3-5 |
| `webhook_create` | Webhooks created | 3 |
| `webhook_delete` | Webhooks deleted | 3 |
| `emoji_create` | Emojis created | 10 |
| `emoji_delete` | Emojis deleted | 3 |
| `emoji_update` | Emojis modified | 5 |
| `invite_create` | Invites created | 10 |
| `invite_delete` | Invites deleted | 10 |
| `vanity_update` | Vanity URL changed | 1 |

### Example Configuration

```bash
# Enable the system
[p]antinuke toggle on

# Set role and channel
[p]antinuke quarantine role @Quarantined
[p]antinuke logchannel #security-logs

# Configure thresholds
[p]antinuke threshold channel_delete 2
[p]antinuke threshold role_delete 1
[p]antinuke threshold ban_add 3
[p]antinuke threshold webhook_create 2
[p]antinuke threshold vanity_update 1

# Set punishment to ban for serious offenses
[p]antinuke punishment ban

# Set time window to 15 seconds
[p]antinuke timewindow 15
```

## Commands Reference

### Main Command Group

All commands are under the `[p]antinuke` group (alias: `[p]an`).

### Configuration Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke` | Show AntiNuke status and settings |
| `[p]antinuke toggle <on/off>` | Enable or disable AntiNuke |
| `[p]antinuke logchannel [channel]` | Set or view the log channel |
| `[p]antinuke timewindow <seconds>` | Set the action counting time window |
| `[p]antinuke punishment <type>` | Set punishment type (quarantine/kick/ban) |

### Threshold Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke threshold` | View all current thresholds |
| `[p]antinuke threshold <action> <count>` | Set threshold for an action |
| `[p]antinuke threshold reset` | Reset all thresholds to defaults |

### Trust Management Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke trust` | View trusted users and roles |
| `[p]antinuke trust adduser <user>` | Add a user to the trust list |
| `[p]antinuke trust removeuser <user>` | Remove a user from the trust list |
| `[p]antinuke trust addrole <role>` | Add a role to the trust list |
| `[p]antinuke trust removerole <role>` | Remove a role from the trust list |

### Quarantine Management Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke quarantine` | View quarantine settings |
| `[p]antinuke quarantine role [role]` | Set or view the quarantine role |
| `[p]antinuke quarantine list` | List all currently quarantined users |
| `[p]antinuke quarantine restore <user>` | Unquarantine a user and restore their roles |
| `[p]antinuke quarantine kickbots <on/off>` | Toggle auto-kicking bot accounts that trigger protection |

### Utility Commands

| Command | Description |
|---------|-------------|
| `[p]antinuke settings` | Display all AntiNuke configuration |
| `[p]antinuke reset` | Reset all settings to defaults |

## Trust System

The trust system allows you to whitelist certain users and roles that will bypass all AntiNuke monitoring.

### Who is Automatically Trusted?

- **Server Owner**: Always trusted, cannot be removed
- **Bot Itself**: Always trusted (the AntiNuke bot)

### Adding Trusted Users

```bash
# Trust a specific user
[p]antinuke trust adduser @AdminUser

# Trust all members with a specific role
[p]antinuke trust addrole @Administrators
```

### Best Practices for Trust

1. **Limit Trusted Roles**: Only trust roles that require dangerous permissions
2. **Regular Audits**: Periodically review the trust list
3. **Role Hierarchy**: Ensure trusted roles are high in the hierarchy
4. **Documentation**: Keep track of why each user/role is trusted

### Trust Recommendations

**Recommended Trusted Roles:**
- Administrator
- Moderator (if they need to ban/kick frequently)
- Bot Manager

**Not Recommended to Trust:**
- Regular member roles
- Trial moderator roles
- Any role with frequent member turnover

## Quarantine System

### How Quarantine Works

When a user triggers AntiNuke:

1. **Role Backup**: All user's current roles are saved to Config
2. **Atomic Strip**: User's roles are replaced with only the quarantine role
3. **Notification**: Alert is sent to the log channel
4. **Bot Handling**: If the offender is a bot, it can be auto-kicked

### Quarantine Role Requirements

The quarantine role should have:
- ❌ No dangerous permissions
- ❌ Cannot mention @everyone or @here
- ❌ Cannot add reactions
- ❌ Cannot send messages in most channels
- ✅ Position below the bot's highest role
- ✅ Distinctive color for visibility

### Creating a Quarantine Role

```bash
# Create the role
[p]createrole Quarantined

# Configure the role (manual or via Discord settings)
# - Remove all permissions
# - Set a distinctive color (e.g., dark red)
# - Position below bot's role

# Set it as the quarantine role
[p]antinuke quarantine role @Quarantined
```

### Restoring Users

When you unquarantine a user:

```bash
[p]antinuke quarantine restore @UserName
```

This will:
1. Remove the quarantine role
2. Restore all previously saved roles
3. Log the restoration

### Manual Quarantine

You can manually quarantine users (requires manage_roles permission):

```bash
# Not directly available - use Discord's role management
# Or use other moderation cogs
```

## Monitored Actions

### Channel Actions

| Event | Audit Log Action | Default Threshold |
|-------|------------------|-------------------|
| Channel Created | `CHANNEL_CREATE` | 5 |
| Channel Deleted | `CHANNEL_DELETE` | 2 |
| Channel Updated | `CHANNEL_UPDATE` | 5 |

**What triggers channel_update:**
- Name changes
- Permission overwrites changes
- Position changes
- Topic changes
- NSFW toggle
- Slow mode changes

### Role Actions

| Event | Audit Log Action | Default Threshold |
|-------|------------------|-------------------|
| Role Created | `ROLE_CREATE` | 5 |
| Role Deleted | `ROLE_DELETE` | 2 |
| Role Updated | `ROLE_UPDATE` | 3 |

**Special: Dangerous Permission Detection**

The system specifically monitors for dangerous permissions being added:
- `administrator`
- `manage_guild`
- `manage_roles`
- `manage_channels`
- `ban_members`
- `kick_members`
- `manage_webhooks`
- `manage_emojis`
- `mention_everyone`
- `manage_permissions`
- `manage_thread`
- `moderate_members`

If any of these permissions are granted to a role, it counts as a `role_update` action.

### Member Actions

| Event | Audit Log Action | Default Threshold |
|-------|------------------|-------------------|
| Member Banned | `MEMBER_BAN_ADD` | 3 |
| Member Unbanned | `MEMBER_BAN_REMOVE` | 5 |
| Member Kicked | `MEMBER_KICK` | 3 |

### Webhook Actions

| Event | Audit Log Action | Default Threshold |
|-------|------------------|-------------------|
| Webhook Created | `WEBHOOK_CREATE` | 3 |
| Webhook Deleted | `WEBHOOK_DELETE` | 3 |

### Emoji Actions

| Event | Audit Log Action | Default Threshold |
|-------|------------------|-------------------|
| Emoji Created | `EMOJI_CREATE` | 10 |
| Emoji Deleted | `EMOJI_DELETE` | 3 |
| Emoji Updated | `EMOJI_UPDATE` | 5 |

### Invite Actions

| Event | Audit Log Action | Default Threshold |
|-------|------------------|-------------------|
| Invite Created | `INVITE_CREATE` | 10 |
| Invite Deleted | `INVITE_DELETE` | 10 |

### Vanity URL

| Event | Audit Log Action | Default Threshold |
|-------|------------------|-------------------|
| Vanity URL Changed | `INTEGRATION_UPDATE` | 1 |

**Note**: Vanity URL changes are detected via `on_guild_update` event. This is highly sensitive as vanity URL theft is a common attack vector.

## Best Practices

### 1. Start Conservative

Begin with higher thresholds and lower them based on your server's needs:

```bash
# Conservative starting point
[p]antinuke threshold channel_delete 5
[p]antinuke threshold role_delete 3
[p]antinuke threshold ban_add 10
```

### 2. Layer Your Protection

Combine AntiNuke with other security measures:
- Verification levels (Settings → Safety Setup)
- Role hierarchy management
- 2FA requirement for moderators
- Audit log monitoring

### 3. Regular Reviews

Monthly tasks:
- Review the trust list
- Check quarantine logs
- Adjust thresholds based on activity
- Verify log channel is accessible

### 4. Test Your Setup

After configuration, test with a trusted user:
1. Have them perform actions near the threshold
2. Verify alerts appear in the log channel
3. Confirm quarantine works correctly
4. Test role restoration

### 5. Document Your Configuration

Keep a record of:
- Current thresholds and why they were chosen
- Trusted users/roles and justification
- Quarantine role ID and permissions
- Log channel location

### 6. Emergency Procedures

Prepare for false positives:
1. Know how to quickly unquarantine users
2. Have a backup communication channel
3. Document the `[p]antinuke toggle off` command for emergencies

### 7. Role Hierarchy

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
1. Is AntiNuke enabled? `[p]antinuke toggle`
2. Is the quarantine role set? `[p]antinuke quarantine role`
3. Is the user trusted? `[p]antinuke trust`
4. Are thresholds too high? `[p]antinuke threshold`
5. Does the bot have required permissions?

### False Positives

**Symptoms**: Legitimate actions trigger quarantine

**Solutions**:
1. Increase thresholds: `[p]antinuke threshold <action> <higher_value>`
2. Trust the user/role: `[p]antinuke trust adduser @User`
3. Increase time window: `[p]antinuke timewindow 15`

### Audit Log Not Working

**Symptoms**: Actions detected but actor not identified

**Checks**:
1. Does bot have `view_audit_log` permission?
2. Is the bot's role high enough in hierarchy?
3. Are audit logs enabled in server settings?

### Quarantine Role Not Applied

**Symptoms**: User triggered but roles not stripped

**Checks**:
1. Is quarantine role set? `[p]antinuke quarantine role`
2. Is bot's role above the user's highest role?
3. Does bot have `manage_roles` permission?
4. Is the quarantine role below bot's role?

### Roles Not Restored

**Symptoms**: Unquarantine doesn't restore previous roles

**Checks**:
1. Were roles saved? Check if user was properly quarantined
2. Is bot's role above the roles being restored?
3. Do the roles still exist?

### Log Channel Not Receiving Messages

**Symptoms**: No alerts in log channel

**Checks**:
1. Is log channel set? `[p]antinuke logchannel`
2. Can bot send messages in that channel?
3. Can bot embed links in that channel?

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

**Q: What's the recommended punishment type?**  
A: For most servers, `quarantine` is recommended as it allows review before action. Use `ban` for high-security servers.

**Q: Should I enable bot kicking?**  
A: Yes, unless you have bots that legitimately perform administrative actions. Rogue bots are a common attack vector.

**Q: What time window should I use?**  
A: 10-15 seconds is recommended. Too short and coordinated attacks might slip through; too long and legitimate actions might trigger false positives.

### Trust System Questions

**Q: Can I trust everyone with a specific permission?**  
A: No, you must trust by user or role. Consider creating a "Trusted Admin" role.

**Q: What if a trusted account is compromised?**  
A: Remove them from trust immediately. The server owner can always override.

**Q: Do trusted users' actions get logged?**  
A: Currently, trusted users' actions bypass the system entirely and are not logged.

### Quarantine Questions

**Q: Can I customize the quarantine message?**  
A: Currently, no. The log message format is standardized.

**Q: What if someone needs to be permanently quarantined?**  
A: Use Discord's built-in timeout or ban features for permanent restrictions.

**Q: Can quarantined users see channels?**  
A: That depends on your channel permissions. Configure the quarantine role's permissions accordingly.

### Technical Questions

**Q: How much RAM does the action cache use?**  
A: Minimal. Each action entry is ~50 bytes. Even with 10,000 actions, it's under 1MB.

**Q: What happens to data if I reload the cog?**  
A: Configuration is persisted. In-memory action counts are reset (intentional behavior).

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
