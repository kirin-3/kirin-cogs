# Taboo Access

A cog that manages access to taboo content channels through an interactive opt-in/opt-out system.

## What It Does

This cog provides a self-service role assignment system for sensitive or taboo content access:
- **"Let me in!"** button to request access (requires confirmation)
- **"Let me out!"** button to remove access instantly
- Confirmation modal to ensure users understand what they're agreeing to
- Automatic role assignment and removal

## Commands

All commands require the **Administrator** permission or **Manage Server** permission. `settaboorole` additionally checks
that the invoker may grant the chosen role: unless you are the guild owner, you need the **Manage Roles** permission
and the role must be below your own top role.

### `sendtaboo`
Sends the taboo access control buttons to the channel. Users can interact with these buttons to manage their access.

**Usage:**
```
[ p ] sendtaboo
```

### `settaboorole`
Sets the role that will be assigned when users request taboo content access.

The role must be assignable: managed and default (`@everyone`) roles are refused, and so is any role at or above the
bot's top role.

**Usage:**
```
[ p ] settaboorole <role>
```

**Example:**
```
[ p ] settaboorole @Taboo Access
```

## How Members Use It

### Gaining Access
1. Click the **"Let me in!"** button (green)
2. A modal dialog appears asking you to confirm by typing `yes` or `i agree`
3. Upon successful confirmation, you receive the taboo access role
4. You now have access to taboo content channels

### Removing Access
1. Click the **"Let me out!"** button (red)
2. The taboo access role is immediately removed
3. You no longer have access to taboo content channels

## Setup for Administrators

1. Create a role for taboo content access in your server settings
2. Set the role: `[ p ] settaboorole @YourTabooRole`. A default role (`1319776542099767316`) is configured out of the
   box, so this step is only needed on other servers or to change it.
3. Post the control buttons in an appropriate channel: `[ p ] sendtaboo`
4. Configure channel permissions to restrict taboo content channels to the taboo access role

## Notes

- The confirmation phrase is case-insensitive: `yes`, `Yes`, `I Agree`, `i agree` all work
- Users can remove their own access at any time without admin intervention
- The bot needs permission to assign and remove roles from members
- Role must exist and be properly configured for the system to work
- If the role is not found, users receive an error message to contact an admin
