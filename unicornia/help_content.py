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
            "• **Economy**: Earn currency by chatting and trading.\n"
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
            "• **Chatting**: You earn a small amount of currency per message.\n"
            "• **Daily**: Claim your daily reward with `[p]timely`.\n"
            "• **Pickups**: Look out for currency drops in chat!"
        ),
        "commands": [
            "`[p]balance` - Check your wallet and bank balance.",
            "`[p]timely` - Claim your daily reward.",
            "`[p]pay <user> <amount>` - Send money to another user.",
            "`[p]bank deposit <amount>` - Move money to your bank.",
            "`[p]bank withdraw <amount>` - Move money to your wallet.",
            "`[p]leaderboard` - See the richest users.",
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
            "`[p]bet <amount> <choice>` - Play Dice (High/Low/Number).",
            "`[p]cf <amount> <heads/tails>` - Coin Flip.",
            "`[p]rps <amount> <choice>` - Rock, Paper, Scissors.",
            "`[p]slots <amount>` - Slot Machine.",
            "`[p]mines <amount>` - Minesweeper game.",
            "`[p]rakeback` - Claim a percentage of your losses back.",
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
            "`[p]rank` - View your rank card and progress.",
            "`[p]levels` - View the server leaderboard.",
            "`[p]level rewards` - See available level-up rewards.",
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
            "`[p]shop buy <item>` - Purchase an item directly.",
            "`[p]inventory` - View your purchased items.",
            "`[p]use <item>` - Use an item from your inventory.",
        ],
    },
    "club": {
        "title": "🏰 Clubs",
        "emoji": "🏰",
        "description": (
            "Create or join a Club to socialize and compete with others.\n"
            "Clubs have their own bank, levels, and chat channels."
        ),
        "commands": [
            "`[p]club create` - Create a new club.",
            "`[p]club join` - Join a club.",
            "`[p]club info` - View club details.",
            "`[p]club deposit` - Contribute to your club's bank.",
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
            "`[p]waifu transfer <user>` - Transfer ownership.",
            "`[p]waifu divorce` - Release a waifu.",
            "`[p]waifus` - List your waifus.",
        ],
    },
    "nitro": {
        "title": "🚀 Nitro Shop",
        "emoji": "🚀",
        "description": (
            "Exchange massive amounts of currency for real Discord Nitro rewards.\n"
            "Stock is limited and manually replenished."
        ),
        "commands": ["`[p]nitro` - Open the Nitro shop menu.", "`[p]nitro stock` - Check current availability."],
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
        ],
    },
}
