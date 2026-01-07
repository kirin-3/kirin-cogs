# Patron Cog

Syncs Discord roles and awards currency from a Google Sheet (supporting Patreon, BuyMeACoffee, or manual entries).

## Features

- **Google Sheets Integration**: Reads data directly from a "Master Sheet" of your donors.
- **Unified Management**: Handle Patreon, BuyMeACoffee, and PayPal donors in one place.
- **Smart Role Sync**: 
  - Automatically grants **Active Role** to active patrons.
  - Automatically moves expired/cancelled patrons to **Former Role**.
  - Downgrades users who are removed from the sheet.
- **Advanced Currency Rewards**:
  - Automatically calculates rewards based on donation amount.
  - Supports **Annual Pledges** by distributing the reward monthly over 12 months.
  - Applies percentage bonuses for higher tiers (5%, 10%, 15%, 20%).
- **European Currency Support**: Handles `€5,00` and `$5.00` formats correctly.

## Setup Guide

### 1. Google Cloud Setup (One-time)
1.  Go to the [Google Cloud Console](https://console.cloud.google.com/).
2.  Create a new project (e.g., "Discord Bot Sheets").
3.  Enable the **Google Sheets API**.
4.  Create a **Service Account** and download the **JSON Key**.
5.  Rename the key file to `service_account.json`.
6.  **Upload** this file to your bot's `patron/` folder (`patron/service_account.json`).

### 2. Prepare Your Sheet
Create a Google Sheet with the following headers (order doesn't matter, names must match):

| Column Name | Description | Example |
|-------------|-------------|---------|
| `Discord` | The Discord username of the patron | `kirin_dev` |
| `Patron Status` | Must be "Active patron" to get rewards | `Active patron` |
| `Pledge Amount` | The donation amount (currency symbol optional) | `€10.00` or `10,00` |
| `Charge Frequency`| "Monthly" or "Annual" | `Monthly` |
| `Last Charge Date`| Date string (any format distinct per charge) | `2024-05-01` |

**Share** this sheet (Editor access) with the **client email** found inside your `service_account.json` file.

### 3. Bot Configuration
Load the cog and configure the settings:

```
[p]load patron
[p]patronset setup <SHEET_ID_FROM_URL>
[p]patronset roles @ActivePatron @FormerPatron
[p]patronset logchannel #bot-logs
```

## Usage

### Automatic Sync
The bot checks the sheet **every hour**. 
- It adds roles to new patrons.
- It removes roles from cancelled patrons.
- It awards currency if a new charge is detected (or if it's the next month of an annual pledge).

### Manual Sync
You can force a sync immediately:
```
[p]patronset sync
```

## Reward Logic

**Base Rate:** 3,000 currency per 1 unit (e.g., $1 = 3000).

**Bonuses:**
- ≥ 5: +5%
- ≥ 10: +10%
- ≥ 20: +15%
- ≥ 40: +20%

**Annual Pledges:**
If `Charge Frequency` contains "Annual", the bot divides the amount by 12. It then awards this monthly equivalent **every 30 days** for 12 months (or until a new charge date appears).

## Troubleshooting

- **Bot not updating roles?** Check if the username in the `Discord` column matches exactly.
- **"Service account not found"?** Ensure `service_account.json` is in the correct folder.
- **Race conditions?** The bot uses a lock to prevent manual syncs from interfering with background syncs.
