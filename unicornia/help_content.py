"""
Content for the Unicornia interactive help system.
"""

HELP_CONTENT = {
    "intro": {
        "title": "🦄 Welcome to Unicornia",
        "emoji": "🦄",
        "description": (
            "**Unicornia** is a complete ecosystem for your server, featuring economy, leveling, gambling, and more!\n\n"
            "**Features:**\n"
            "• **Economy**: Earn currency from daily claims, chat drops, and level-ups.\n"
            "• **Gambling**: Test your luck with various games.\n"
            "• **Leveling**: Gain XP and unlock role rewards.\n"
            "• **Shop**: Buy items, roles, and upgrades.\n"
            "• **Clubs**: Join forces with other members.\n"
            "• **Waifus**: Collect and trade characters.\n\n"
            "*Select a category from the dropdown menu below to learn more about a specific system.*"
        ),
        "commands": [],
    },
    "economy": {
        "title": "💰 Economy System",
        "emoji": "💰",
        "description": (
            "Manage your wealth in Unicornia. The currency is **Slut points** (<:slut:686148402941001730>).\n"
            "You can keep money in your **Wallet** (for spending) or **Bank** (for safekeeping).\n\n"
            "**Earning Money:**\n"
            "• **Daily**: Claim your daily reward with `[p]timely`.\n"
            "• **Pickups**: Chatting can make currency drop in chat. Grab it with `[p]pick`!\n"
            "• **Level-ups**: Some levels pay a currency reward."
        ),
        "commands": [
            "`[p]balance` - Check your wallet and bank balance.",
            "`[p]timely` - Claim your daily reward.",
            "`[p]economy give <amount> <user>` - Send money to another user.",
            "`[p]bank deposit <amount>` - Move money to your bank.",
            "`[p]bank withdraw <amount>` - Move money to your wallet.",
            "`[p]baltop` - See the richest users.",
        ],
    },
    "gambling": {
        "title": "🎲 Gambling",
        "emoji": "🎲",
        "description": (
            "Risk it all to win big! Unicornia offers several ways to gamble your currency.\n"
            "**Warning**: The house always has an edge (but you get Rakeback!)."
        ),
        "commands": [
            "`[p]betroll <amount>` - Roll a number from 1 to 100.",
            "`[p]betflip <amount> <heads/tails>` - Coin Flip.",
            "`[p]rps <choice> <amount>` - Rock, Paper, Scissors.",
            "`[p]slots <amount>` - Slot Machine.",
            "`[p]blackjack <amount>` - Blackjack.",
            "`[p]luckyladder <amount>` - Lucky Ladder.",
            "`[p]mines <amount> [mines]` - Minesweeper game.",
            "`[p]duel <user> <amount>` - Challenge another player to a staked RPS duel.",
            "Blackjack messages accept capped spectator wagers until the player acts.",
            "`[p]economy rakeback` - Claim a percentage of your losses back (blackjack excluded).",
        ],
    },
    "level": {
        "title": "🆙 Leveling System",
        "emoji": "🆙",
        "description": (
            "Earn XP by being active in the server. As you level up, you can unlock special roles and currency rewards.\n\n"
            "**Mechanics:**\n"
            "• XP is gained per message (with a cooldown).\n"
            "• Voice activity also grants XP (if enabled).\n"
            "• Double XP channels grant 2x rewards."
        ),
        "commands": [
            "`[p]xp [user]` - View your rank card and progress.",
            "`[p]xplb` - View the server leaderboard.",
        ],
    },
    "shop": {
        "title": "🛒 Shop",
        "emoji": "🛒",
        "description": (
            "Spend your hard-earned currency on items and roles.\n"
            "The shop contains different categories of items to enhance your experience."
        ),
        "commands": [
            "`[p]shop` - Open the interactive shop browser.",
            "`[p]shop buy <id>` - Purchase an item directly.",
            "`[p]inventory` - View your purchased items.",
            "`[p]xpshop backgrounds` - Browse rank card backgrounds.",
            "`[p]xpshop use <item>` - Use a background you own.",
        ],
    },
    "club": {
        "title": "🏰 Clubs",
        "emoji": "🏰",
        "description": (
            "Create or join a Club to socialize and compete with others.\n"
            "Clubs earn XP together and compete on the club leaderboard."
        ),
        "commands": [
            "`[p]club create <name>` - Create a new club.",
            "`[p]club apply <name>` - Apply to join a club.",
            "`[p]club info [name]` - View club details.",
            "`[p]club leaderboard` - See the top clubs.",
            "`[p]club leave` - Leave your current club.",
        ],
    },
    "waifu": {
        "title": "👰 Waifus",
        "emoji": "👰",
        "description": (
            "Claim users as your waifus/husbandos! The price increases every time a waifu is claimed.\n"
            "Protect your waifus to prevent others from stealing them."
        ),
        "commands": [
            "`[p]waifu claim <user>` - Buy a user as your waifu.",
            "`[p]waifu transfer <waifu> <new owner>` - Transfer ownership.",
            "`[p]waifu divorce <user>` - Release a waifu.",
            "`[p]waifu list` - List your waifus.",
        ],
    },
    "nitro": {
        "title": "🚀 Nitro Shop",
        "emoji": "🚀",
        "description": (
            "Exchange massive amounts of currency for real Discord Nitro rewards.\n"
            "Stock is limited and manually replenished."
        ),
        "commands": ["`[p]nitroshop` - Open the Nitro shop and see current stock."],
    },
    "market": {
        "title": "📈 Stock Market",
        "emoji": "📈",
        "description": (
            "Invest in the dynamic Unicornia Stock Market.\nBuy low, sell high, and watch your portfolio grow!"
        ),
        "commands": [
            "`[p]stock list` - View active stocks and prices.",
            "`[p]stock buy <ticker> <amount>` - Buy shares.",
            "`[p]stock sell <ticker> <amount>` - Sell shares.",
            "`[p]stock portfolio` - View your holdings.",
            "`[p]stock dividends` - View your dividend history by stock and period.",
        ],
    },
}
