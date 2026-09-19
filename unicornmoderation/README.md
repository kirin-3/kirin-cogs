# UnicornModeration

A small Papers, Please–themed moderation cog for a single server. Every ban, kick, mute, unmute, or warn posts a retro "citation" image (protocol violation, with the user and reason rendered on a passport-stamp card) into a hardcoded log channel.

## Commands

All commands are guild-only and prefix-only.

| Command | Permission | Description |
|---------|-----------|-------------|
| `[p]ban <member> [reason]` | Ban Members | Ban a member and delete their messages from the last hour. |
| `[p]kick <member> [reason]` | Kick Members | Kick a member from the server. |
| `[p]mute <member> [reason]` | Manage Roles | Mute a member (adds the hardcoded Muted role). |
| `[p]unmute <member> [reason]` | Manage Roles | Unmute a member (removes the Muted role). |
| `[p]warn <member> <reason>` | Kick Members | Warn a member; the warning is stored. |
| `[p]warnings <member>` | Kick Members | List a member's warnings (moderator, reason, date). |

## Setup

- Requires the `pillow` dependency (installed automatically from `info.json`).
- The **Muted role** (hardcoded ID in the cog source) and the **log channel** (hardcoded ID) must exist for mute/citation features to work; edit the constants in `unicorn_moderation.py` for a new server.
- Citation images are generated from the bundled `base.png` and `04B_03__.TTF` font.

## Data Storage

Member-scoped warnings (moderator, reason, timestamp). Warnings are removed via Red's user-data deletion hook.
