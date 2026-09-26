# Patron Cog

Gives supporters a role and monthly currency from **Patreon** (API polled hourly) and **Buy Me a Coffee** (webhooks).
Requires the Unicornia cog for currency. It works for one hard-coded server (`GUILD_ID` in `patron.py`).

## How it works

- **Patreon**: every hour the cog reads the campaign's members. A new charge with status `Paid` starts a run of
  periods: one for monthly pledges, twelve for annual ones (a reward every 30 days, each for a twelfth of the charge). The patron's Discord account comes
  from Patreon's Discord connection.
- **Buy Me a Coffee memberships and monthly donations**: reward every 30 days from the start while the membership is
  `active`; yearly memberships pay a twelfth of the amount each period. The role stays until the paid period ends.
- **Buy Me a Coffee one-time donations**: one reward and the Active role for 30 days. Refunds are posted to the log
  channel; currency already awarded is not taken back.
- **Roles**: anyone with an active payment gets the Active role; anyone who paid before gets the Former role instead.
  Members the cog has no payment record for are never touched.
- **Linking**: a payment without a Discord account (every Buy Me a Coffee supporter, and patrons who have not connected
  Discord on Patreon) is announced once in the log channel and held. `[p]patronset link @user <email>` releases it.
  A staff link also overrides the Discord account a patron connected on Patreon.

Rewards are 3,000 currency per unit of money (dollar, euro…), with bonuses of 5% from 5, 10% from 10, 15% from 20 and 20%
from 40. Each payment has its own operation key in Unicornia, so retries and replayed webhooks never pay twice.

## Setup

1. **Patreon**: register a client at <https://www.patreon.com/portal/registration/register-clients>, then:
   ```
   [p]set api patreon access_token,<creator access token>,refresh_token,<creator refresh token>,client_id,<client id>,client_secret,<client secret>
   ```
   The cog refreshes the access token itself when it expires. Connect Patreon's Discord integration on your creator
   page so patrons' Discord IDs are available.
2. **Webhook host**: point a Cloudflare-proxied hostname at the server and proxy it to the cog:
   ```
   hooks.unicornia.net {
       reverse_proxy 127.0.0.1:8014
   }
   ```
3. **Buy Me a Coffee**: under Integrations → Webhooks, add `https://hooks.unicornia.net/bmc` with the membership,
   recurring donation and donation events, then:
   ```
   [p]set api buymeacoffee webhook_secret,<signing secret>
   ```
4. **Roles and log channel**:
   ```
   [p]patronset roles @Supporter @FormerSupporter
   [p]patronset logchannel #supporter-log
   ```
   The bot needs Manage Roles and a role above both.
5. **Existing Buy Me a Coffee members** (once each): the webhook only sees members from their next event, so add
   everyone who joined before it:
   ```
   [p]patronset bmcadd @user <email> <amount> [month|year]
   ```
   Their current period counts as paid; rewards start with the next one. When BMC later sends an event for that email,
   the webhook takes the membership over without paying it twice.

The first Patreon sync records every current charge as already paid, so switching from the Google Sheet does not pay
anyone twice for the current month.

## Commands (bot owner)

| Command | What it does |
| --- | --- |
| `[p]patronset creds` | Shows the credential and webhook setup |
| `[p]patronset roles <active> <former>` | Sets the supporter roles |
| `[p]patronset logchannel <channel>` | Sets the channel for rewards, unlinked payments and refunds |
| `[p]patronset sync` | Polls Patreon now and pays anything due |
| `[p]patronset link <user> <email>` | Links a Patreon/Buy Me a Coffee email to a Discord user |
| `[p]patronset unlink <email>` | Removes a link |
| `[p]patronset unlinked` | Lists payments not linked to anyone (shows emails, so run it in a staff channel) |
| `[p]patronset bmcadd <user> <email> <amount> [month\|year]` | Adds a Buy Me a Coffee member who joined before the webhook |
