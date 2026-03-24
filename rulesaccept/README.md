# Rules Accept

A cog that manages rule acceptance for server members using an interactive button and modal system.

## What It Does

This cog allows server administrators to create a rule acceptance system where members must:
1. Click a button to indicate they've read the rules
2. Type a confirmation phrase in a modal dialog
3. Receive a role automatically upon successful acceptance

The system logs all rule acceptances to a designated channel for administrative tracking.

## Commands

All commands require **Manage Guild** permissions or **Admin** role.

### `sendrules`
Sends the rules acceptance button to the channel. Members can click this button to begin the acceptance process.

**Usage:**
```
[ p ] sendrules
```

### `setrole`
Sets the role that will be assigned to members when they accept the rules.

**Usage:**
```
[ p ] setrole <role>
```

**Example:**
```
[ p ] setrole @Member
```

## How Members Use It

1. When the rules button is posted, members click **"I have read and accept the rules."**
2. A modal dialog appears asking them to type exactly: `I agree to the rules.`
3. Upon successful submission:
   - The member receives the configured role
   - They receive a confirmation message
   - They're informed about additional role requirements from the roles channel

## Setup for Administrators

1. Set the role to assign: `[ p ] setrole @YourMemberRole`
2. Post the rules button in your rules channel: `[ p ] sendrules`
3. Ensure the bot has permission to:
   - Send messages in the rules channel
   - Assign roles to members
   - Send messages to the logging channel (ID: 1422656113077256322)

## Notes

- The acceptance phrase is case-sensitive and must match exactly: `I agree to the rules.` or `I Agree To The Rules.`
- All rule acceptances are logged with the member's ID and what they typed
- Members are informed they need additional roles from the roles channel for full server access
