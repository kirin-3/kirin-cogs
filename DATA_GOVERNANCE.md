# Data governance

This repository treats Discord IDs as personal identifiers even when no username is stored. Each cog's `info.json` describes its persistent and externally processed data. Cogs with user-linked persistent records implement Red's `red_delete_data_for_user` hook.

## Retention and deletion

| Cog | Persistent or externally processed data | Deletion behavior |
| --- | --- | --- |
| AntiNuke | Trusted user IDs; quarantine role snapshots, reasons, and timestamps | Removes trust and quarantine entries |
| Confess | Confession text posted to Discord; author ID/content audit messages sent to bot owners | No local per-user record; Discord retention and deletion tools apply |
| CustomCommand | User limits, command ownership, triggers, and responses | Removes limits and commands owned by the user |
| CustomEmoji | User limits and emoji ownership | Removes limits and ownership records |
| CustomRoleColor | User-to-role management assignments | Removes the assignment |
| Honeypot | Guild-scoped user IDs, prior role IDs, and quarantine timestamps | Removes the user's quarantine records from every guild |
| NitroAward | Guild/member boost timestamps and legacy boost markers | Clears member and legacy records |
| Patron | Discord-ID charge dates and annual-payment progress | Removes local tracking; Unicornia financial entries follow its policy |
| Profile | Questionnaire answers, picture URLs, message IDs, and timestamps | Clears member-scoped and legacy user-scoped records |
| RulesAccept | Acceptance member ID and submitted text posted to a Discord log channel | No local per-user record; Discord log-retention policy applies |
| Suggest | Author IDs, suggestion text, message IDs, status, and review reason | Removes suggestions authored by the user |
| Tickets | Owner IDs, answers, channel/message metadata, avatar URL, timestamps, and lifecycle state | Removes ticket tracking and blacklist entries; Discord messages/channels remain subject to server moderation policy |
| UnicornAI | User opt-out preference | Clears the preference; channel history is processed transiently by the configured provider |
| UnicornModeration | Guild/member warning history | Clears warnings in every guild |
| Unicornia | XP, balances, inventory, games, relationships, and financial history | Removes operational state; anonymizes accounting rows that must remain internally consistent |
| UniMod | In-memory message buffers; optional redacted diagnostic response | Buffers vanish on unload; diagnostic files expire within one hour and are removed on unload/restart |

Configuration-only cogs do not retain per-user records. Some cogs send user-provided content to Discord or a configured external service; their metadata statements describe that processing even when the cog itself does not retain a copy.

## Financial audit records

Unicornia exports the complete available transaction history without a hardcoded row limit. On deletion, accounting rows are retained only when deleting them would invalidate the ledger. Direct user IDs and free-form metadata in those rows are replaced with a non-user sentinel or removed. Operation keys are replaced with unique internal deletion keys.

## Operator checklist

Before release, run the metadata contract test and the relevant deletion tests. When adding a new stored field, update the cog's `info.json`, this inventory, and its deletion/export implementation in the same change.
