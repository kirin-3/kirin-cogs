# Rules Accept

A cog that manages rule acceptance for server members using an interactive button and modal system.

## What It Does

This cog allows server administrators to create a rule acceptance system where members must:
1. Click a button to indicate they've read the rules
2. Type a confirmation phrase and pick their primary role in a modal dialog
3. Receive the member role and their primary role automatically upon successful acceptance

The system logs all rule acceptances to a designated channel for administrative tracking.

## Commands

All commands require the **Administrator** permission or **Manage Server** permission. `setrole` additionally checks
that the invoker may grant the chosen role: unless you are the guild owner, you need the **Manage Roles** permission
and the role must be below your own top role.

### `sendrules`
Sends the rules acceptance button to the channel. Members can click this button to begin the acceptance process.

**Usage:**
```
[ p ] sendrules
```

### `setrole`
Sets the role that will be assigned to members when they accept the rules.

The role must be assignable: managed and default (`@everyone`) roles are refused, and so is any role at or above the
bot's top role.

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
2. A modal dialog appears asking them to type `I agree to the rules` and to pick a primary role from a dropdown
3. Upon successful submission:
   - The member receives the configured role and the primary role they picked
   - They receive a confirmation message that points at the roles channel for changing or adding roles

## Setup for Administrators

1. Set the role to assign: `[ p ] setrole @YourMemberRole`. A default role (`686098839651876908`) is configured
   out of the box, so this step is only needed on other servers or to change it.
2. Post the rules button in your rules channel: `[ p ] sendrules`
3. Ensure the bot has permission to:
   - Send messages in the rules channel
   - Assign roles to members
   - Send messages to the logging channel (ID: 1422656113077256322)

## Notes

- The acceptance phrase is `I agree to the rules`. Case, extra spaces, surrounding quotes and a closing period or
  exclamation mark are ignored.
- The primary roles offered are the hardcoded `PRIMARY_ROLE_IDS` in `rulesaccept.py`, shown in that order with their
  current names. Roles that no longer exist are left out. On a server with none of them the modal asks for the phrase
  only, and the confirmation tells the member to pick a role in the roles channel.
- All rule acceptances are logged with the member's ID and what they typed. The role they picked is not logged.
- Members with the Muted role (`686252873583165520`) are refused, so accepting the rules again can't undo a mute
