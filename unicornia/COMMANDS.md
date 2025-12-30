# Unicornia Commands

Here is a comprehensive list of all commands available in the Unicornia cog.

## Administration
Commands for configuring the Unicornia system.

| Command | Description | Permission |
| :--- | :--- | :--- |
| `[p]unicornia` | Base command for Unicornia configuration. Alias: `uni` | |
| `[p]unicornia config <setting> <value>` | Configure global Unicornia settings. | Bot Owner |
| `[p]unicornia status` | Check the current status and configuration of Unicornia systems. | |
| `[p]unicornia gen channel <operation> <channel>` | Add or remove a channel for currency generation. Operation: `add` or `remove`. | Bot Owner |
| `[p]unicornia gen list` | List currency generation channels. | |
| `[p]unicornia guild` | Base command for guild-specific configuration. | Admin |
| `[p]unicornia guild xp include <channel>` | Add a channel to the XP whitelist. | Admin |
| `[p]unicornia guild xp exclude <channel>` | Remove a channel from the XP whitelist. | Admin |
| `[p]unicornia guild xp listchannels` | List all channels in the XP whitelist. | Admin |
| `[p]unicornia guild rolereward <level> <role> [remove]` | Set a role reward for reaching a specific level. Set `remove` to True to remove role instead of adding. | Admin |
| `[p]unicornia guild removerolereward <level> <role>` | Remove a configured role reward. | Admin |
| `[p]unicornia guild currencyreward <level> <amount>` | Set a currency reward for reaching a specific level. | Admin |
| `[p]unicornia guild listcurrencyrewards` | List all configured currency rewards. | Admin |
| `[p]unicornia guild listrolerewards` | List all configured role rewards. | Admin |

## Clubs
Social groups that users can join, level up, and manage.

| Command | Description | Permission |
| :--- | :--- | :--- |
| `[p]club` | Base command for club management. | |
| `[p]club create <name>` | Create a new club (costs currency). | |
| `[p]club info [name]` | View information about a club. Alias: `profile`. | |
| `[p]club leave` | Leave your current club. | |
| `[p]club apply <name>` | Apply to join an existing club. | |
| `[p]club accept <user>` | Accept a user's application. | Club Owner |
| `[p]club reject <user>` | Reject a user's application. Alias: `deny`. | Club Owner |
| `[p]club kick <user>` | Kick a member from the club. | Club Owner/Server Mod |
| `[p]club ban <user>` | Ban a member from the club. | Club Owner/Server Mod |
| `[p]club unban <user>` | Unban a member from the club. | Club Owner/Server Mod |
| `[p]club transfer <new_owner>` | Transfer club ownership to another member. | Club Owner |
| `[p]club applicants` | View pending club applications. Alias: `apps`. | Club Owner |
| `[p]club bans` | View banned members. | Club Owner |
| `[p]club rename <new_name>` | Rename the club. | Club Owner/Server Mod |
| `[p]club icon <url>` | Set the club's icon URL. | Club Owner/Server Mod |
| `[p]club banner <url>` | Set the club's banner URL. | Club Owner/Server Mod |
| `[p]club desc <description>` | Set the club's description. | Club Owner/Server Mod |
| `[p]club disband` | Disband the club permanently. | Club Owner/Server Mod |
| `[p]club leaderboard` | View the club XP leaderboard. Alias: `lb`. | |

## Economy & Currency
Manage your wallet, bank, and transactions.

| Command | Description | Permission |
| :--- | :--- | :--- |
| `[p]economy` | Base command for economy features. Aliases: `econ`, `money`. | |
| `[p]economy balance [user]` | Check your or another user's wallet and bank balance. Aliases: `bal`, `wallet`. | |
| `[p]balance [user]` | Global shortcut for balance check. Aliases: `bal`, `$`, `€`, `£`. | |
| `[p]economy give <amount> <user>` | Give currency to another user from your wallet. | |
| `[p]economy timely` | Claim your daily currency reward. Alias: `daily`. | |
| `[p]timely` | Global shortcut to claim daily reward. Alias: `daily`. | |
| `[p]economy history [user]` | View recent transaction history. Aliases: `transactions`, `tx`. | |
| `[p]economy stats [user]` | View detailed gambling statistics. Alias: `gambling`. | |
| `[p]economy rakeback` | Check and claim your gambling rakeback (5% of losses). Alias: `rb`. | |
| `[p]economy leaderboard` | View the global currency leaderboard. Aliases: `lb`, `top`. | |
| `[p]baltop` | Global shortcut for economy leaderboard. Alias: `ballb`. | |
| `[p]economy award <amount> <user>` | Award currency to a user (generated out of thin air). | Bot Owner |
| `[p]economy take <amount> <user>` | Take currency from a user. | Bot Owner |
| `[p]economy bank [user]` | View bank information for a user. | |
| `[p]pick` | Global shortcut to pick up generated currency from chat. | |
| `[p]currency pick [password]` | Pick up generated currency from chat. | |
| `[p]bank` | Base command for banking. | |
| `[p]bank deposit <amount>` | Deposit currency from wallet to bank. Alias: `dep`. | |
| `[p]bank withdraw <amount>` | Withdraw currency from bank to wallet. Alias: `with`. | |
| `[p]bank balance` | Check your bank balance. Alias: `bal`. | |

## Gambling
Games of chance to win (or lose) currency. All gambling commands have top-level shortcuts.

| Command | Description |
| :--- | :--- |
| `[p]gambling` | Base command for gambling. Alias: `gamble`. |
| `[p]gambling betroll <amount>` | Roll dice (1-100). Roll 66+ to win. Alias: `roll`. Shortcut: `[p]betroll`. |
| `[p]gambling rps <choice> [amount]` | Play Rock-Paper-Scissors against the bot. Alias: `rockpaperscissors`. Shortcut: `[p]rps`. |
| `[p]gambling slots <amount>` | Play the slot machine. Shortcut: `[p]slots`. |
| `[p]gambling blackjack <amount>` | Play a game of Blackjack (21). Aliases: `bj`, `21`. Shortcut: `[p]blackjack`. |
| `[p]gambling betflip <amount> <heads/tails>` | Bet on a coin flip. Alias: `bf`. Shortcut: `[p]betflip`. |
| `[p]gambling luckyladder <amount>` | Climb the lucky ladder for increasing multipliers. Alias: `ladder`. Shortcut: `[p]luckyladder`. |

## Leveling
Track your activity and earn rewards.

| Command | Description |
| :--- | :--- |
| `[p]level` | Base command for leveling. Aliases: `lvl`, `xp`. |
| `[p]level check [user]` | Check your (or another user's) level, rank, and view XP card. Alias: `me`. |
| `[p]level leaderboard` | View the server XP leaderboard. Aliases: `lb`, `top`. |
| `[p]xplb` | Global shortcut for XP leaderboard. |

## Nitro Shop
Buy Discord Nitro with currency.

| Command | Description | Permission |
| :--- | :--- | :--- |
| `[p]nitroshop` | Open the Nitro Shop to purchase Discord Nitro subscriptions. | |
| `[p]nitrostock <type> <amount>` | Add or remove stock for Nitro items. Types: `boost`, `basic`. | Bot Owner |
| `[p]nitroprice <type> <price>` | Set the price for Nitro items. Types: `boost`, `basic`. | Bot Owner |

## Shop
Buy roles, items, and XP card customizations.

| Command | Description | Permission |
| :--- | :--- | :--- |
| `[p]shop` | Base command for the item shop. Alias: `store`. | |
| `[p]shop list` | List all available items in the server shop. Aliases: `items`, `view`. | |
| `[p]shop buy <index_or_id>` | Purchase an item from the shop. | |
| `[p]shop info <index_or_id>` | View detailed info about a shop item. | |
| `[p]shop add <type> <price> <name> [details]` | Add a new item to the shop. Types: role, item, effect, other. | Admin/Manage Roles |
| `[p]shop edit <item_id> <field> <value>` | Edit a shop item. Fields: name, price, type, role, req. | Admin/Manage Roles |
| `[p]shop remove <item_id>` | Remove an item from the shop. Aliases: `delete`, `del`. | Admin/Manage Roles |
| `[p]inventory` | View your purchased shop items. Aliases: `inv`, `bag`. | |
| `[p]xpshop` | Base command for the XP background shop. Alias: `xps`. | |
| `[p]xpshop backgrounds` | List available XP card backgrounds. Aliases: `bg`, `bgs`. | |
| `[p]xpshop buy <key>` | Buy a new background for your XP card. | |
| `[p]xpshop use <key>` | Set a purchased background as active. | |
| `[p]xpshop owned` | View your owned backgrounds. Aliases: `inventory`, `inv`. | |
| `[p]xpshop reload` | Reload the XP shop configuration. | Bot Owner |
| `[p]xpshop give <user> <key>` | Give an XP background to a user. | Bot Owner |
| `[p]xpshopbuy <type> [key]` | Shortcut to buy XP shop items. | |

## Waifus
Claim and trade virtual waifus (other users).

| Command | Description | Permission |
| :--- | :--- | :--- |
| `[p]waifu` | Base command for the waifu system. Alias: `wf`. | |
| `[p]waifu claim <user> [price]` | Claim a user as your waifu. | |
| `[p]waifu transfer <member> <new_owner>` | Transfer a waifu to another user. | |
| `[p]waifu reset <member>` | Reset a waifu to unclaimed status. | Bot Owner |
| `[p]waifu divorce <member>` | Divorce a waifu (frees them). | |
| `[p]waifu gift <item_name> <member>` | Gift an item to a waifu to change their value. | |
| `[p]waifu gifts` | List all available gifts for waifus. | |
| `[p]waifu info [member]` | View information about a waifu (price, owner, items). | |
| `[p]waifu list [member]` | List waifus owned by a user. Alias: `my`. | |
| `[p]waifu leaderboard` | View the most expensive waifus. Aliases: `lb`, `top`. | |
| `[p]waifu price <member> <new_price>` | Set a new price for your waifu. | Waifu Owner |
| `[p]waifu affinity [user]` | Set whom the waifu has an affinity for. | |
| `[p]gifts` | Global shortcut to list available gifts. | |