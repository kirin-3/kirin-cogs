# Cutie of the Month Contest (COTM)

A Discord bot cog that manages the Cutie of the Month contest on the Unicornia server. This cog provides a comprehensive dashboard for contest information, handles voting, calculates results, and distributes rewards to winners.

## Features

- **Interactive Dashboard**: A persistent message with tabs for contest information, entry terms, prizes, and voting instructions
- **Check Standings Button**: Any user can press "Check Standings" on the dashboard to see the current top 10 standings (ephemeral reply). The tally is shared and refreshed at most every 5 minutes, so repeated presses don't re-read the entries channel
- **Vote Counting**: Automated tallying of votes using reaction counts in the contest channel
- **Leaderboard Display**: Shows the top 10 contestants based on vote counts. Each person is ranked once, by their best entry
- **Reward Distribution**: Automatic distribution of special currency rewards to contest winners
- **Persistent Interface**: Dashboard remains functional across bot restarts

## Commands

### Admin Commands

- `[p]contest [contest_number]` or `[p]cotm [contest_number]`
  - Posts the contest dashboard to the current channel
  - Optional contest_number parameter specifies which contest number to display
  - Requires administrator permissions

- `[p]contestcount <channel> [emote] [show_invalid] [voter_server_age] [*other_emotes]`
  - Counts reactions in a specified channel and displays a leaderboard
  - `channel`: The channel to count votes in
  - `emote`: The emoji to count (defaults to the contest vote emoji)
  - `show_invalid`: Whether to show invalid vote counts (defaults to false)
  - `voter_server_age`: Timedelta filter for minimum server membership to count votes
  - `*other_emotes`: Additional emojis to count as votes. A voter counts once per entry, whichever of the emojis they used

### Owner Commands

- `[p]cotmreward <channel> [contest_number]`
  - Counts votes in the specified channel and pays the currency rewards for the places listed in `data/prizes.txt` (1st to 9th, amounts in `COTM_REWARDS`)
  - The first run saves the places and amounts for that contest number before paying anyone. Running it again (for example after a failed deposit) pays those same saved places, only what is still missing, even if votes changed since
  - Each winner is paid at most once per contest (`cotm:<contest>:<user>` Unicornia operation key)
  - Once a contest's places are saved, running it for that contest number on a different channel is refused
  - `contest_number` defaults to the number set with `[p]contest`; make sure it is the current contest, or the saved results of an earlier contest with the same number are used
  - Requires the Unicornia cog to be loaded for currency distribution
  - Restricted to bot owners only

## Setup

1. Configure the relevant channels and constants in `const.py` to match your server's needs:
   - Entries channel ID
   - Winners channel ID
   - Cutie role ID
   - Other server-specific constants

2. Ensure the bot has proper permissions in the designated channels:
   - Read Messages, Send Messages, and Embed Links in the channels where the dashboard is posted
   - Read Message History in the entries channel (the cog reads reactions; it never adds any)

3. Load the cog using `[p]load cotm`

## Usage

### For Contestants
- Submit contest entries in the designated entries channel (as configured in the constants)
- Entries must comply with the contest terms and conditions listed in the dashboard
- Use the dashboard's "Check Standings" button to see the current top 10 at any time

### For Voters
- Navigate to the contest entries channel
- React to your favorite entries with the designated vote emoji (defaults to the uwuheart emoji)
- Each reaction counts as one vote toward the contestant's total

### For Administrators
- Use `[p]contest [number]` to post the contest dashboard to any channel
- Monitor entries to ensure they meet contest requirements
- Use `[p]contestcount` to check the current standings during the contest

### For Bot Owners
- Use `[p]cotmreward` to distribute rewards to the winners at the end of the contest
- This command is only available to bot owners and requires the Unicornia currency system to be operational

## Contest Terms & Conditions

The contest has specific rules that are displayed in the dashboard:
- Minimum level requirement (Level 15/Gold)
- One entry per person
- Real photos only (no AI-generated images or drawings)
- No NSFW content
- Restrictions for previous winners within the past 6 months
- And more as defined in the contest terms

## Prizes

The top contestants receive various rewards including:
- Gift cards (for 1st place)
- Special server role (Cutie of the Month)
- Custom server role (for 1st place)
- Currency rewards for 1st to 9th place
- Inclusion in special commands and channels (with consent)

## Voting System

- Voting is done through reactions in the entries channel
- Only specific emoji reactions count as valid votes
- A minimum-membership age for voters can be applied by passing `voter_server_age` to `[p]contestcount`; it is not a server-wide setting, and the "Check Standings" button and `[p]cotmreward` count votes without any age filter

## Technical Details

- The dashboard uses Discord's V2 components for interactive navigation
- The dashboard updates automatically across bot restarts
- The system supports multiple emoji types for vote counting