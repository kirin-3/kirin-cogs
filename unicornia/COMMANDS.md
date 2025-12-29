# Unicornia Commands

Here is a comprehensive list of all commands available in the Unicornia cog.

## Administration
Commands for configuring the Unicornia system.

| Command | Description | Permission |
| :--- | :--- | :--- |
| `[p]unicornia` | Base command for Unicornia configuration. Alias: `uni` | |
| `[p]unicornia config <setting> <value>` | Configure global Unicornia settings (e.g., enable/disable systems, set rates). | Bot Owner |
| `[p]unicornia status` | Check the current status and configuration of Unicornia systems. | |
| `[p]unicornia gen channel <operation> <channel>` | Add or remove a channel for currency generation. Operation: `add` or `remove`. | Bot Owner |
| `[p]unicornia gen list` | List currency generation channels. | |
| `[p]unicornia guild` | Base command for guild-specific configuration. | Admin |
| `[p]unicornia guild xpenabled <true/false>` | Enable or disable the XP system for the current server. | Admin |
| `[p]unicornia guild levelupmessages <true/false>` | Enable or disable level-up messages for the current server. | Admin |
| `[p]unicornia guild levelupchannel [channel]` | Set the channel for level-up messages (leave empty for current channel). | Admin |
| `[p]unicornia guild excludechannel <channel>` | Exclude a channel from XP gain. | Admin |
| `[p]unicornia guild includechannel <channel>` | Re-include a channel for XP gain. | Admin |
| `[p]unicornia guild rolereward <level> <role>` | Set a role reward for reaching a specific level. | Admin |
| `[p]unicornia guild currencyreward <level> <amount>` | Set a currency reward for reaching a specific level. | Admin |

## Clubs
Social groups that users can join, level up, and manage.

| Command | Description |
| :--- | :--- |
| `[p]club` | Base command for club management. |
| `[p]club create <name>` | Create a new club (costs currency). |
| `[p]club info [name]` | View information about a club (yours or another). Alias: `profile`. |
| `[p]club leave` | Leave your current club. |
| `[p]club apply <name>` | Apply to join an existing club. |
| `[p]club accept <user>` | Accept a user's application. (Club Owner only) |
| `[p]club reject <user>` | Reject a user's application. Alias: `deny`. (Club Owner only) |
| `[p]club kick <user>` | Kick a member from the club. (Club Owner/Server Mod) |
| `[p]club ban <user>` | Ban a member from the club. (Club Owner/Server Mod) |
| `[p]club unban <user>` | Unban a member from the club. (Club Owner/Server Mod) |
| `[p]club transfer <new_owner>` | Transfer club ownership to another member. (Club Owner only) |
| `[p]club applicants` | View pending club applications. Alias: `apps`. (Club Owner only) |
| `[p]club bans` | View banned members. (Club Owner only) |
| `[p]club rename <new_name>` | Rename the club. (Club Owner/Server Mod) |
| `[p]club icon <url>` | Set the club's icon URL. (Club Owner/Server Mod) |
| `[p]club banner <url>` | Set the club's banner URL. (Club Owner/Server Mod) |
| `[p]club desc <description>` | Set the club's description. (Club Owner/Server Mod) |
| `[p]club disband` | Disband the club permanently. (Club Owner/Server Mod) |
| `[p]club leaderboard` | View the club XP leaderboard. Alias: `lb`. |

## Economy & Currency
Manage your wallet, bank, and transactions.

| Command | Description |
| :--- | :--- |
| `[p]economy` | Base command for economy features. Aliases: `econ`, `money`. |
| `[p]economy balance [user]` | Check your or another user's wallet and bank balance. Aliases: `bal`, `wallet`. |
| `[p]balance [user]` | Global shortcut for balance check. Aliases: `bal`, `$`, `€`, `£`. |
| `[p]economy give <amount> <user>` | Give currency to another user from your wallet. |
| `[p]economy timely` | Claim your daily currency reward. Alias: `daily`. |
| `[p]timely` | Global shortcut to claim daily reward. Alias: `daily`. |
| `[p]economy history [user]` | View recent transaction history. Aliases: `transactions`, `tx`. |
| `[p]economy stats [user]` | View detailed gambling statistics. Alias: `gambling`. |
| `[p]economy rakeback` | Check and claim your gambling rakeback (5% of losses). Alias: `rb`. |
| `[p]economy leaderboard` | View the global currency leaderboard. Aliases: `lb`, `top`. |
| `[p]economy award <amount> <user>` | Award currency to a user (generated out of thin air). (Bot Owner only) |
| `[p]economy take <amount> <user>` | Take currency from a user. (Bot Owner only) |
| `[p]currency pick` | Pick up generated currency from chat. |
| `[p]pick` | Global shortcut to pick up currency. |
| `[p]bank` | Base command for banking. |
| `[p]bank deposit <amount>` | Deposit currency from wallet to bank. Alias: `dep`. |
| `[p]bank withdraw <amount>` | Withdraw currency from bank to wallet. Alias: `with`. |
| `[p]bank balance` | Check your bank balance. Alias: `bal`. |

## Gambling
Games of chance to win (or lose) currency.

| Command | Description |
| :--- | :--- |
| `[p]gambling` | Base command for gambling. Alias: `gamble`. |
| `[p]gambling betroll <amount>` | Roll dice (1-100). Roll 66+ to win. Alias: `roll`. |
| `[p]gambling rps <choice> [amount]` | Play Rock-Paper-Scissors against the bot. Alias: `rockpaperscissors`. |
| `[p]gambling slots <amount>` | Play the slot machine. |
| `[p]gambling blackjack <amount>` | Play a game of Blackjack (21). Aliases: `bj`, `21`. |
| `[p]gambling betflip <amount> <heads/tails>` | Bet on a coin flip. Alias: `bf`. |
| `[p]gambling luckyladder <amount>` | Climb the lucky ladder for increasing multipliers. Alias: `ladder`. |

## Leveling
Track your activity and earn rewards.

| Command | Description |
| :--- | :--- |
| `[p]level` | Base command for leveling. Aliases: `lvl`, `xp`. |
| `[p]level check [user]` | Check your (or another user's) level, rank, and view XP card. Alias: `me`. |
| `[p]level leaderboard` | View the server XP leaderboard. Aliases: `lb`, `top`. |

## Shop
Buy roles, items, and XP card customizations.

| Command | Description |
| :--- | :--- |
| `[p]shop` | Base command for the item shop. Alias: `store`. |
| `[p]shop list` | List all available items in the server shop. Aliases: `items`, `view`. |
| `[p]shop buy <index_or_id>` | Purchase an item from the shop. |
| `[p]shop info <index_or_id>` | View detailed info about a shop item. |
| `[p]shop add <type> <price> <name> [details]` | Add a new item to the shop. Types: role, command, effect, other. (Admin/Manage Roles) |
| `[p]shop edit <item_id> <field> <value>` | Edit a shop item. Fields: name, price, type, role, command, req. (Admin/Manage Roles) |
| `[p]shop remove <item_id>` | Remove an item from the shop. Aliases: `delete`, `del`. (Admin/Manage Roles) |
| `[p]xpshop` | Base command for the XP background shop. Alias: `xps`. |
| `[p]xpshop backgrounds` | List available XP card backgrounds. Aliases: `bg`, `bgs`. |
| `[p]xpshop buy <key>` | Buy a new background for your XP card. |
| `[p]xpshop use <key>` | Set a purchased background as active. |
| `[p]xpshop owned` | View your owned backgrounds. Aliases: `inventory`, `inv`. |
| `[p]xpshop reload` | Reload the XP shop configuration. (Bot Owner only) |
| `[p]xpshop config` | View XP shop configuration info. (Bot Owner only) |

## Waifus
Claim and trade virtual waifus (other users).

| Command | Description |
| :--- | :--- |
| `[p]waifu` | Base command for the waifu system. Alias: `wf`. |
| `[p]waifu claim <user> [price]` | Claim a user as your waifu. |
| `[p]waifu transfer <waifu> <new_owner>` | Transfer a waifu to another user. |
| `[p]waifu reset <waifu>` | Reset a waifu to unclaimed status. (Bot Owner only) |
| `[p]waifu divorce <waifu>` | Divorce a waifu (frees them). |
| `[p]waifu gift <item_name> <waifu>` | Gift an item to a waifu to change their value. |
| `[p]waifu gifts` | List all available gifts for waifus. |
| `[p]gifts` | Global shortcut to list available gifts. |
| `[p]waifu info <waifu>` | View information about a waifu (price, owner, items). |
| `[p]waifu list [user]` | List waifus owned by a user. Alias: `my`. |
| `[p]waifu leaderboard` | View the most expensive waifus. Aliases: `lb`, `top`. |
| `[p]waifu price <waifu> <new_price>` | Set a new price for your waifu. (Waifu Owner only) |
| `[p]waifu affinity <waifu> <user>` | Set whom the waifu has an affinity for. |