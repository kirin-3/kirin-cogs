# VerifyUser

A small single-server verification cog. Members holding a specific authorized role can verify other members, granting them a verification role.

## Usage

```
[p]verifyuser <target_user>
```

The command is hybrid — it works as a slash command (`/verifyuser`) as well. Replies are ephemeral.

## Permissions

- The invoking member must hold the hardcoded **authorized role**.
- The bot needs **Manage Roles**.

Extensive safety checks are performed before the role is granted: role hierarchy for both the bot and the invoker, and self/bot/guild-owner/already-verified targets are rejected.

## Setup

The two role IDs are hardcoded constants in `verifyuser.py` and must be edited in code for a new server:

- `AUTHORIZED_ROLE_ID` — role allowed to run the command
- `VERIFICATION_ROLE_ID` — role granted to verified members

## Data Storage

This cog stores no data.
