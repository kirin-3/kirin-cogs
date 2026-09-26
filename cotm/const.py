import logging
from pathlib import Path

LOGGER_LEVEL = logging.INFO

# These roles and channels are specific to Unicornia Server
CUTIE_OF_THE_MONTH_ROLE_ID = 707303996389589045
CUTIE_ROLE_MENTION = f"<@&{CUTIE_OF_THE_MONTH_ROLE_ID}>"

ENTRIES_CHANNEL_ID = 782019562795302934
ENTRIES_CHANNEL_MENTION = f"<#{ENTRIES_CHANNEL_ID}>"
WINNERS_CHANNEL_ID = 823595067997945907
WINNERS_CHANNEL_MENTION = f"<#{WINNERS_CHANNEL_ID}>"

# COLOR = 3553598
UNICORNIA_BOT_COLOR = 5778572

FOOTER_TEXT = "Unicornia | Cutie of the Month Contest {contest_number}"
FOOTER_ICON_URL = r"https://i.imgur.com/jy8AWEI.png"

DATA_PATH = Path(__file__).parent / "data"

CONTEST_TITLE = "Unicornia Cutie of the Month Contest"
CONTEST_DESCRIPTION = DATA_PATH / "contest.txt"

TERMS_TITLE = "Entry Terms"
TERMS_DESCRIPTION = DATA_PATH / "terms.txt"

PRIZES_TITLE = "Prizes"
PRIZES_DESCRIPTION = DATA_PATH / "prizes.txt"

VOTES_TITLE = "How to cast votes"
VOTES_DESCRIPTION = DATA_PATH / "votes.txt"

# emoji IDs
# SLUT_EMOJI_ID = 686148402941001730
# CROSS_NO_EMOJI_ID = 729330876114141215
# TICK_YES_EMOJI_ID = 729330852747542568
# UNICORN_DOT_EMOJI_ID = 965576604212396092
# UWU_HEART_EMOJI_ID = 862261325077544971
COTM_VOTE_EMOJI = "<:uwuheart:862261325077544971>"

# Reward payouts for 1st through 9th place; keep in step with data/prizes.txt
COTM_REWARDS = [20000, 25000, 20000, 15000, 10000, 10000, 10000, 10000, 10000]

# The public "Check Standings" button re-reads the whole entries channel, so share one tally for this long
STANDINGS_CACHE_SECONDS = 300
