# Privacy Policy

**Applies to:** the Unicornia Discord bot (application ID `695701050656817172`)
**Operator:** kirin-3
**Contact:** kirin@unicornia.net
**Effective:** 16 September 2026
**Last updated:** 25 September 2026

---

## 1. Summary

Unicornia is a private, self-hosted [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) instance operated for a single Discord community. It is not a public bot, it is not listed in any bot directory, and it is not invited to servers other than our own.

The bot stores Discord user IDs linked to whatever you actually use — your XP and currency balance, your profile answers, your support tickets, your warnings. It keeps a copy of messages posted in the server for 7 days, so that messages Discord erases when someone is banned can still be reviewed by staff, and it reads messages in a small number of specific channels for automated moderation. It reads presence information only to name temporary voice channels and to decide whether to offer a mobile spoiler helper.

You can see what is stored about you, export it, and delete it at any time using the commands in [section 8](#8-your-rights), without asking a human.

## 2. Who is responsible

This bot is operated by kirin-3 on self-managed infrastructure. Questions, complaints, and data requests go to **kirin@unicornia.net**, or to a support ticket in the server. We aim to respond within 30 days.

## 3. What we collect, and why

### 3.1 Account identifiers

We store your **Discord user ID** — the numeric ID Discord assigns you, not your username — linked to records for the features you use. We treat this ID as personal data even where no name is attached.

### 3.2 Member and role information

We read your server membership and roles to:

- grant access roles when you accept the server rules and the adult-content policy;
- assign, enforce limits on, and remove self-service cosmetic and colour roles;
- detect when you begin boosting the server, so a boost reward is granted exactly once;
- detect mass-kick, mass-ban, and unauthorised bot-addition events, and quarantine the responsible account;
- close your open support tickets when you leave the server;
- restrict leaderboards to current members;
- verify that contest voters meet a minimum account-tenure requirement.

Quarantine records retain a snapshot of the roles you held, so that staff can restore them if the action is reversed.

### 3.3 Message content

The bot reads message content only for the purposes below. Apart from the 7-day ban-evidence copy, it does not retain messages generally, and it does not build profiles from conversation.

- **Ban evidence.** Every message a member posts in the server is copied to the bot's own database with its channel, time, attachment filenames (not the files), latest edit, and whether it was deleted. Copies are deleted automatically after 7 days. When a member is banned, Discord can erase up to a week of their messages without telling anyone; the bot therefore copies that member's messages from the week before the ban into a ban record, together with the moderator and reason, so staff can see what the ban was for. Ban records are kept as moderation records (see [section 6](#6-retention) and [section 8](#8-your-rights)).
- **Automod rules.** Every message and edit is checked against rules the bot owner sets, such as word lists, invite links and spam limits, and your nickname, display name and username are checked when you join and when they change. When a rule matches, the bot can delete the message, warn, mute, time out, ban, or change your nickname. It keeps a log of its newest 250 actions with the time, your user ID and name, the channel, the rules that matched and what it did, but **never the message text**. To catch spam, it keeps your recent messages in memory for up to an hour, the longest spam window; they are never written to disk and are discarded on restart.
- **Automated moderation.** In a staff-selected list of channels, recent messages are held in a short in-memory buffer and scored locally for sentiment. When a buffer crosses a threshold, it is sent to a language model (see [section 5](#5-third-parties)) to classify harassment, hate speech, or targeted abuse. If flagged, moderators receive an alert containing the relevant excerpt. **Buffers are never written to disk and are discarded on restart.**
- **Channel rules.** In channels restricted to images or to Tenor links, message text and attachments are inspected so that non-conforming posts can be removed.
- **Raid honeypot.** A hidden channel exists that legitimate members have no reason to post in. Posting there records the message text and attachment filenames into the staff audit log as the evidence supporting the resulting ban or quarantine.
- **Moderation logging.** Edited and deleted messages in public channels are copied to a private staff-only channel so moderators can review content that was removed before they saw it.
- **Deleted-message recall.** A short-lived in-memory cache holds the most recent deleted or edited message per channel so staff can recall it. It expires after 30 seconds by default and is never written to disk.
- **Commands and triggers.** Text-prefixed commands, member-authored text triggers, and keyword auto-responses require reading the message that invokes them.

Message content is **not** used to train any machine-learning or AI model.

### 3.4 Presence and activity

The bot reads your Discord status and current activity for exactly two features:

- naming a temporary voice channel after the game you are playing, falling back to your username when no game is detected;
- determining whether you are on a mobile client, so that a spoiler-tagging helper is offered only to mobile users.

**Presence and activity data is never stored, logged, or transmitted anywhere.** It is read from the live gateway cache at the moment of the event and then discarded. If you do not want your activity used this way, disable *"Display current activity as a status message"* in your own Discord privacy settings, which removes it from the data Discord sends us at all.

### 3.5 Staff web site

Staff can review ban records and the automod rules and action log on a private web site, `staff.unicornia.net`, after logging in with Discord. The login reads only the staff member's Discord user ID and whether their account has two-factor authentication. The login session is held in memory, never written to disk, and ends after 12 hours, on logout, or when the bot restarts. Members who are not staff cannot log in.

### 3.6 Content you submit deliberately

Profile questionnaire answers, suggestions, confessions, support-ticket answers, custom command triggers and responses, rules-acceptance text, and image-generation prompts are stored or posted as the feature requires. Roleplay settings store your consent choices (whether you are public, a servant, or selective) and the user IDs you add as your owner, allowed users, or blocked users. Confessions and rules acceptances are posted to Discord channels rather than retained in a local database; once posted, Discord's retention and your server's moderation policy apply.

### 3.7 Supporter payments

If you support the server on Patreon or Buy Me a Coffee, the bot receives your name there, your email address, your pledge amount and status, and your charge dates, from the Patreon API and Buy Me a Coffee's webhooks. It links them to your Discord account (from Patreon's Discord connection, or by staff matching your email) to give you the supporter role and currency rewards. Payment card details never reach the bot.

## 4. What we do not do

We do not sell, rent, or share your data for advertising. We do not use it to train AI models. We do not combine it with data from outside Discord, except linking supporter payments to your account (section 3.7). We do not access your direct messages except where you send one to the bot itself.

## 5. Third parties

The bot is hosted on infrastructure we control. The following external services receive data in the course of specific features:

| Service | What it receives | Which feature |
| --- | --- | --- |
| **Discord** | Everything, necessarily — Discord is the platform | All |
| **NanoGPT** | Message excerpts from allowlisted channels, for abuse classification | Automated moderation |
| **AI Horde** | The image prompt you supply | Image generation (free tier) |
| **Modal** | The image prompt you supply | Image generation (premium tier) |
| **popcat.xyz** | The target member's Discord avatar URL | Avatar image commands |
| **Cloudflare** | Traffic to the staff web site, including the ban records staff view there and staff members' IP addresses; Buy Me a Coffee payment notifications on their way to the bot | Staff web site; supporter rewards |

These services process the data to return a result; we do not authorise them to retain it for their own purposes, and we send them no more than the feature requires. Some features fetch content *from* third parties (question prompts, reaction GIFs) without sending any user data; those are not listed above because nothing about you leaves the bot.

If a new feature introduces a new recipient, this table is updated before that feature is enabled.

## 6. Retention

| Category | Retained |
| --- | --- |
| Moderation message buffers | In memory only; discarded on restart |
| Deleted-message cache | 30 seconds by default; in memory only |
| Copies of server messages (ban evidence) | 7 days, then deleted automatically |
| Ban records, with the banned member's messages from the week before the ban | Kept as moderation records until removed on request (see [section 8](#8-your-rights)) |
| Automod action log | The newest 250 actions; older entries are dropped automatically |
| Automod spam history | In memory only; at most one hour, and discarded on restart |
| Staff web site login sessions | In memory only; at most 12 hours |
| Presence and activity | Not retained at all |
| Diagnostic moderation output | Up to one hour, then deleted automatically |
| XP, currency, inventory, profiles, tickets, warnings, roleplay settings | Until you request deletion or the record is no longer needed |
| Quarantine role snapshots | Until the quarantine is resolved and the record cleared |
| Boost timestamps | Retained to prevent duplicate awards for the same boost |
| Supporter payment records (section 3.7) | Until you request deletion |
| Financial transaction records | Retained for ledger integrity; identifiers are removed on deletion (see [section 8](#8-your-rights)) |

Content posted into Discord channels — confessions, suggestions, moderation logs, honeypot evidence — persists as Discord messages and is governed by Discord's retention and by server moderation policy, not by this bot.

## 7. Security

The bot runs on infrastructure controlled by the operator, with access limited to the operator. Credentials and API tokens are held in Red's own token store and are not present in the public source repository. No system is perfectly secure; we do not promise that it is.

## 8. Your rights

Every member can exercise these directly, without contacting staff. Replace `[p]` with the bot's command prefix.

| Command | What it does |
| --- | --- |
| `[p]mydata whatdata` | Explains what the bot stores and why |
| `[p]mydata getmydata` | Returns a copy of your stored data |
| `[p]mydata forgetme` | Deletes your data from every module that holds any |
| `[p]mydata 3rdparty` | Lists each loaded module's own data statement |

You can also open a support ticket in the server, or email **kirin@unicornia.net**.

**One limitation, stated plainly:** the in-server economy keeps a transaction ledger. Deleting rows outright would leave the ledger internally inconsistent, so on a deletion request those rows are retained with your user ID and any free-form notes replaced by a non-identifying sentinel. The remaining record cannot be linked back to you. Everything else — balances, XP, inventory, profiles, tickets, relationships, warnings, and the 7-day message copies — is removed.

**A second limitation:** if you were banned, `[p]mydata forgetme` keeps the ban record, including your messages from the week before the ban, because it is a moderation record. To have it removed, email **kirin@unicornia.net**. When a Discord account is deleted, its ban records are removed automatically.

## 9. Age

Discord requires users to be at least 13, or older where local law sets a higher minimum. This bot is not directed at children and we do not knowingly retain data from anyone below Discord's minimum age. Some server areas are gated behind an adult-content acceptance step; the bot records that acceptance in order to grant access.

## 10. Community modules

Unicornia runs a mix of modules written by the operator and modules published by the wider Red community. This policy covers the bot's behaviour as a whole, including community modules, because they run under our control and on our infrastructure.

- Modules written by the operator are published at <https://github.com/kirin-3/kirin-cogs>, with a per-module data inventory in [DATA_GOVERNANCE.md](./DATA_GOVERNANCE.md) recording exactly what each one stores and what deletion does to it.
- Community modules publish their own end-user data statements, which `[p]mydata 3rdparty` prints in full. The large majority declare no persistent storage of user data. Those that do process user data materially — moderation logging, the deleted-message cache, and avatar image commands — are described in [section 3](#3-what-we-collect-and-why) and [section 5](#5-third-parties) above rather than left to their own statements.

## 11. Changes

Material changes are announced in the server and reflected in the "Last updated" date above. The revision history of this file is public in the repository, so any change can be inspected and compared.

## 12. Contact

**kirin@unicornia.net** — or a support ticket in the server.
