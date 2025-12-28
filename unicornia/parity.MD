# Nadeko Bot vs Unicornia Command Parity

This document provides a comprehensive comparison of **ALL** Nadeko Bot commands against the `unicornia` cog implementation. `unicornia` is a specialized cog for **Economy** and **XP** migration, so many general-purpose commands are intentionally not implemented as they are covered by Red Bot's core or other cogs.

## Legend
- ✅ : Fully Implemented (Same or similar functionality)
- ⚠️ : Partially Implemented / Configuration Only / Alternative Available
- ❌ : Not Implemented (Out of Scope for this cog)

## 1. Administration Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.imageonlychannel` | Toggle image-only channel | ❌ | Use Red's Filter/Mod |
| `.linkonlychannel` | Toggle link-only channel | ❌ | Use Red's Filter/Mod |
| `.slowmode` | Toggle slowmode | ❌ | Use Red's Mod |
| `.delmsgoncmd` | Toggle delete msg on command | ❌ | Red Core feature |
| `.deafen` | Deafen user | ❌ | Use Red's Voice/Mod |
| `.undeafen` | Undeafen user | ❌ | Use Red's Voice/Mod |
| `.delvoichanl` | Delete voice channel | ❌ | Use Red's Admin |
| `.creatvoichanl` | Create voice channel | ❌ | Use Red's Admin |
| `.deltxtchanl` | Delete text channel | ❌ | Use Red's Admin |
| `.creatxtchanl` | Create text channel | ❌ | Use Red's Admin |
| `.settopic` | Set channel topic | ❌ | Use Red's Admin |
| `.setchanlname` | Set channel name | ❌ | Use Red's Admin |
| `.nsfwtoggle` | Toggle NSFW | ❌ | Use Red's Admin |
| `.edit` | Edit bot message | ❌ | Use Red's EmbedUtils |
| `.delete` | Delete message | ❌ | Use Red's Cleanup |
| `.threadcreate` | Create thread | ❌ | |
| `.threaddelete` | Delete thread | ❌ | |
| `.autopublish` | Auto-publish news | ❌ | |
| `.setnick` | Set nickname | ❌ | Use Red's Mod |
| `.setserverbanner` | Set server banner | ❌ | Use Red's Admin |
| `.setservericon` | Set server icon | ❌ | Use Red's Admin |
| `.autoassignrole` | Auto-assign role on join | ❌ | Use Red's Admin |
| `.cleanupguilddata` | DB Cleanup | ❌ | Migration tool only |
| `.keep` | DB Cleanup Exemption | ❌ | |
| `.sqlselect` | SQL Query | ❌ | Dev tool |
| `.sqlselectcsv` | SQL Query CSV | ❌ | Dev tool |
| `.sqlexec` | SQL Execute | ❌ | Dev tool |
| `.purgeuser` | Purge user data | ❌ | |
| `.deletexp` | Delete all XP | ❌ | |
| `.deletewaifus` | Delete all waifus | ❌ | |
| `.deletewaifu` | Delete user waifu | ❌ | |
| `.deletecurrency` | Delete all currency | ❌ | |
| `.gamevoicechannel` | Game Voice Channel | ❌ | |
| `.boost` | Boost notifications | ❌ | Use Red's Greet |
| `.boostdel` | Boost auto-delete | ❌ | |
| `.boostmsg` | Boost message | ❌ | |
| `.greet` | Welcome messages | ❌ | Use Red's Greet |
| `.greetdel` | Welcome auto-delete | ❌ | |
| `.greetmsg` | Welcome message | ❌ | |
| `.greetdm` | Welcome DM | ❌ | |
| `.greetdmmsg` | Welcome DM message | ❌ | |
| `.bye` | Leave messages | ❌ | Use Red's Greet |
| `.byemsg` | Leave message | ❌ | |
| `.byedel` | Leave auto-delete | ❌ | |
| `.byetest` | Test leave | ❌ | |
| `.greettest` | Test welcome | ❌ | |
| `.greetdmtest` | Test welcome DM | ❌ | |
| `.boosttest` | Test boost | ❌ | |
| `.honeypot` | Honeypot channel | ❌ | |
| `.languageset` | Set language | ❌ | Red Core `[p]set lang` |
| `.langsetdefault` | Set default lang | ❌ | |
| `.languageslist` | List languages | ❌ | |
| `.muterole` | Set mute role | ❌ | Use Red's Mod |
| `.mute` | Mute user | ❌ | Use Red's Mod |
| `.unmute` | Unmute user | ❌ | Use Red's Mod |
| `.chatmute` | Chat mute | ❌ | Use Red's Mod |
| `.chatunmute` | Chat unmute | ❌ | Use Red's Mod |
| `.voicemute` | Voice mute | ❌ | Use Red's Mod |
| `.voiceunmute` | Voice unmute | ❌ | Use Red's Mod |
| `.dpo` | Discord Perm Override | ❌ | Use Red's Permissions |
| `.dpor` | Reset DPO | ❌ | |
| `.dpol` | List DPO | ❌ | |
| `.rotateplaying` | Rotate status | ❌ | Use Red's Status |
| `.addplaying` | Add status | ❌ | |
| `.listplaying` | List status | ❌ | |
| `.removeplaying` | Remove status | ❌ | |
| `.prefix` | Set prefix | ❌ | Red Core `[p]set prefix` |
| `.defprefix` | Default prefix | ❌ | |
| `.antialt` | Anti-alt protection | ❌ | |
| `.antiraid` | Anti-raid protection | ❌ | |
| `.antispam` | Anti-spam protection | ❌ | |
| `.antispamignore` | Ignore antispam | ❌ | |
| `.antilist` | List protections | ❌ | |
| `.prune` | Prune messages | ❌ | Use Red's Cleanup |
| `.prunecancel` | Cancel prune | ❌ | |
| `.reroadd` | Add reaction role | ❌ | Use Red's Admin/ReactRole |
| `.rerolist` | List reaction roles | ❌ | |
| `.reroremove` | Remove reaction role | ❌ | |
| `.rerodeleteall` | Delete all rero | ❌ | |
| `.rerotransfer` | Transfer rero | ❌ | |
| `.setrole` | Give role | ❌ | Use Red's Mod |
| `.removerole` | Remove role | ❌ | Use Red's Mod |
| `.renamerole` | Rename role | ❌ | |
| `.removeallroles` | Remove all roles | ❌ | |
| `.createrole` | Create role | ❌ | |
| `.deleterole` | Delete role | ❌ | |
| `.rolehoist` | Toggle hoist | ❌ | |
| `.rolecolor` | Set role color | ❌ | |
| `.stickyroles` | Sticky roles | ❌ | |
| `.adsarm` | Auto-delete SAR | ❌ | |
| `.asar` | Add Self-Assign Role | ❌ | Use Red's Admin |
| `.sargn` | SAR Group Name | ❌ | |
| `.rsar` | Remove SAR | ❌ | |
| `.lsar` | List SAR | ❌ | |
| `.togglexclsar` | Toggle exclusive SAR | ❌ | |
| `.rolelevelreq` | SAR Level Req | ❌ | |
| `.iam` | Get Role | ❌ | |
| `.iamnot` | Remove Role | ❌ | |
| `.cacheusers` | Cache users | ❌ | |
| `.doas` | Exec as user | ❌ | |
| `.scadd` | Startup cmd add | ❌ | |
| `.acadd` | Auto cmd add | ❌ | |
| `.sclist` | List startup cmds | ❌ | |
| `.aclist` | List auto cmds | ❌ | |
| `.wait` | Wait cmd | ❌ | |
| `.acrm` | Remove auto cmd | ❌ | |
| `.scrm` | Remove startup cmd | ❌ | |
| `.scclear` | Clear startup cmds | ❌ | |
| `.forwardmessages` | Forward DMs | ❌ | |
| `.forwardtoall` | Forward to all | ❌ | |
| `.forwardtochannel` | Forward to channel | ❌ | |
| `.shardstats` | Shard stats | ❌ | |
| `.restartshard` | Restart shard | ❌ | |
| `.leave` | Leave server | ❌ | Use Red's Core |
| `.deleteemptyservers` | Clean servers | ❌ | |
| `.die` | Shutdown | ❌ | Red Core `[p]shutdown` |
| `.restart` | Restart | ❌ | Red Core `[p]restart` |
| `.setname` | Set bot name | ❌ | Red Core `[p]set name` |
| `.setstatus` | Set status | ❌ | Red Core `[p]set status` |
| `.setavatar` | Set avatar | ❌ | Red Core `[p]set avatar` |
| `.setbanner` | Set banner | ❌ | |
| `.setgame` | Set game | ❌ | Red Core `[p]set game` |
| `.setstream` | Set stream | ❌ | Red Core `[p]set stream` |
| `.send` | Send DM | ❌ | Use Red's Core |
| `.stringsreload` | Reload strings | ❌ | |
| `.coordreload` | Reload coord | ❌ | |
| `.logserver` | Log server | ❌ | Use Red's Log |
| `.logignore` | Log ignore | ❌ | |
| `.logevents` | Log events | ❌ | |
| `.log` | Toggle log | ❌ | |
| `.timezones` | List timezones | ❌ | |
| `.timezone` | Set timezone | ❌ | |
| `.warn` | Warn user | ❌ | Use Red's Warnings |
| `.warnexpire` | Warn expire | ❌ | |
| `.warnlog` | Warn log | ❌ | |
| `.warnlogall` | Warn log all | ❌ | |
| `.warndelete` | Delete warn | ❌ | |
| `.warnclear` | Clear warns | ❌ | |
| `.warnpunish` | Warn punish | ❌ | |
| `.warnpunishlist` | Punish list | ❌ | |
| `.ban` | Ban user | ❌ | Use Red's Mod |
| `.banprune` | Ban prune days | ❌ | |
| `.banmessage` | Ban message | ❌ | |
| `.banmsgreset` | Reset ban msg | ❌ | |
| `.banmsgtest` | Test ban msg | ❌ | |
| `.unban` | Unban user | ❌ | Use Red's Mod |
| `.softban` | Softban user | ❌ | Use Red's Mod |
| `.kick` | Kick user | ❌ | Use Red's Mod |
| `.timeout` | Timeout user | ❌ | Use Red's Mod |
| `.massban` | Mass ban | ❌ | Use Red's Mod |
| `.masskill` | Mass kill | ❌ | |
| `.vcrolerm` | VC Role remove | ❌ | |
| `.vcrole` | VC Role set | ❌ | |
| `.vcrolelist` | VC Role list | ❌ | |

## 2. Expressions Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.expr*` | All Expression commands | ❌ | Custom Reactions not implemented |

## 3. Gambling Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.betstats` | Gambling stats | ⚠️ | `[p]economy stats` (Partial) |
| `.timely` | Claim daily | ✅ | `[p]economy timely` |
| `.timelyreset` | Reset daily | ❌ | |
| `.timelyset` | Set daily config | ⚠️ | Config via `[p]unicornia config` |
| `.raffle` | Random user | ❌ | |
| `.raffleany` | Random user (any) | ❌ | |
| `.curtrs` | Transactions | ✅ | `[p]economy history` |
| `.curtr` | Transaction info | ❌ | |
| `.cash` / `.currency` | Check balance | ✅ | `[p]economy balance` |
| `.give` | Give currency | ✅ | `[p]economy give` |
| `.award` | Award currency | ✅ | `[p]economy award` |
| `.take` | Take currency | ✅ | `[p]economy take` |
| `.betroll` | Roll 0-100 | ✅ | `[p]gambling betroll` |
| `.leaderboard` | Currency LB | ✅ | `[p]economy leaderboard` |
| `.rps` | Rock Paper Scissors | ✅ | `[p]gambling rps` |
| `.luckyladder` | Lucky Ladder | ✅ | `[p]gambling luckyladder` |
| `.bettest` | Test betting | ❌ | |
| `.race` | Animal Race | ❌ | |
| `.joinrace` | Join Race | ❌ | |
| `.bank deposit` | Deposit to bank | ✅ | `[p]bank deposit` |
| `.bank withdraw` | Withdraw from bank | ✅ | `[p]bank withdraw` |
| `.bank balance` | Check bank bal | ✅ | `[p]bank balance` |
| `.bank take` | Admin take bank | ❌ | |
| `.bank award` | Admin award bank | ❌ | |
| `.blackjack` | Blackjack | ✅ | `[p]gambling blackjack` |
| `.hit`, `.stand`, `.double` | BJ Actions | ✅ | Interactive buttons in Unicornia |
| `.connect4` | Connect4 | ❌ | |
| `.roll` | Roll dice | ❌ | |
| `.rolluo` | Roll unordered | ❌ | |
| `.nroll` | Roll range | ❌ | |
| `.draw` | Draw card | ❌ | |
| `.drawnew` | Draw new card | ❌ | |
| `.deckshuffle` | Shuffle deck | ❌ | |
| `.betdraw` | Bet on card | ❌ | |
| `.eventstart` | Start event | ❌ | |
| `.flip` | Flip coin | ❌ | |
| `.betflip` | Bet on coin | ✅ | `[p]gambling betflip` |
| `.pick` | Pick currency | ✅ | `[p]currency pick` |
| `.plant` | Plant currency | ❌ | Only automated generation |
| `.gencurrency` | Toggle gen | ⚠️ | Config via `[p]unicornia config` |
| `.gencurlist` | List gen channels | ❌ | |
| `.shop` | List shop | ✅ | `[p]shop list` |
| `.shopbuy` | Buy item | ✅ | `[p]shop buy` |
| `.shopadd` | Add item | ✅ | `[p]shop add` |
| `.shoplistadd` | Add list item | ❌ | |
| `.shopremove` | Remove item | ✅ | `[p]shop remove` |
| `.shopchangeprice` | Change price | ❌ | Use update/remove+add |
| `.shopchangename` | Change name | ❌ | Use update/remove+add |
| `.shopswap` | Swap index | ❌ | |
| `.shopmove` | Move index | ❌ | |
| `.shopreq` | Set requirement | ❌ | |
| `.slot` | Slots | ✅ | `[p]gambling slots` |
| `.waifureset` | Reset waifus | ✅ | `[p]waifu reset` |
| `.waifuclaim` | Claim waifu | ✅ | `[p]waifu claim` |
| `.waifutransfer` | Transfer waifu | ✅ | `[p]waifu transfer` |
| `.divorce` | Divorce waifu | ✅ | `[p]waifu divorce` |
| `.affinity` | Set affinity | ✅ | `[p]waifu affinity` |
| `.waifulb` | Waifu LB | ✅ | `[p]waifu leaderboard` |
| `.waifuinfo` | Waifu stats | ✅ | `[p]waifu info` |
| `.waifugift` | Gift item | ✅ | `[p]waifu gift` / `[p]gifts` |

## 4. Games Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.choose` | Choose option | ❌ | Use Red's General |
| `.8ball` | 8ball | ❌ | Use Red's General |
| `.acrophobia` | Acrophobia game | ❌ | |
| `.cleverbot` | Chatbot | ❌ | |
| `.hangman` | Hangman | ❌ | |
| `.nunchi` | Nunchi game | ❌ | |
| `.typestart` | SpeedTyping | ❌ | |
| `.tictactoe` | TicTacToe | ❌ | |
| `.trivia` | Trivia | ❌ | Use Red's Trivia |

## 5. Help Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.modules` | List modules | ❌ | Use `[p]help` |
| `.commands` | List commands | ❌ | Use `[p]help` |
| `.h` | Command help | ❌ | Use `[p]help` |
| `.gencmdlist` | Gen JSON | ❌ | |
| `.guide` | Guide link | ❌ | |
| `.donate` | Donate link | ❌ | |
| `.patron` | Patron status | ❌ | |
| `.patronmessage` | Patron msg | ❌ | |

## 6. Medusa Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.medusa*` | All Medusa commands | ❌ | Not implemented |

## 7. Music Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.join` | Join VC | ❌ | Use Red's Audio |
| `.destroy` | Leave VC | ❌ | Use Red's Audio |
| `.play` | Play song | ❌ | Use Red's Audio |
| `.queue` | Queue song | ❌ | Use Red's Audio |
| `.volume` | Set volume | ❌ | Use Red's Audio |
| `.next` | Next song | ❌ | Use Red's Audio |
| `.stop` | Stop music | ❌ | Use Red's Audio |
| `.pause` | Pause music | ❌ | Use Red's Audio |
| `.nowplaying` | Now playing | ❌ | Use Red's Audio |
| `.*` | Other Music cmds | ❌ | Use Red's Audio |

## 8. Permissions Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.verbose` | Verbose errors | ❌ | |
| `.permrole` | Perm role | ❌ | |
| `.listperms` | List perms | ❌ | |
| `.srvrcmd` | Server cmd perm | ❌ | Use Red's Permissions |
| `.chnlcmd` | Channel cmd perm | ❌ | Use Red's Permissions |
| `.rolecmd` | Role cmd perm | ❌ | Use Red's Permissions |
| `.usrcmd` | User cmd perm | ❌ | Use Red's Permissions |
| `.userblacklist` | User blacklist | ❌ | Use Red's Core |
| `.cmdcooldown` | Command CD | ❌ | Use Red's Permissions |
| `.filter*` | Filter commands | ❌ | Use Red's Filter |
| `.global*` | Global perms | ❌ | Use Red's Permissions |

## 9. Searches Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.weather` | Weather | ❌ | |
| `.time` | Time | ❌ | |
| `.movie` | Movie search | ❌ | |
| `.randomcat` | Cat image | ❌ | |
| `.randomdog` | Dog image | ❌ | |
| `.google` | Google search | ❌ | |
| `.image` | Image search | ❌ | |
| `.youtube` | YT search | ❌ | |
| `.anime` | Anime search | ❌ | |
| `.manga` | Manga search | ❌ | |
| `.stock` | Stock search | ❌ | |
| `.crypto` | Crypto search | ❌ | |
| `.feed` | RSS Feed | ❌ | |
| `.translate` | Translate | ❌ | |
| `.xkcd` | XKCD | ❌ | |

## 10. Utility Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.say` | Bot say | ❌ | Use Red's Core |
| `.whosplaying` | Who's playing | ❌ | |
| `.inrole` | In role list | ❌ | |
| `.userid` | User ID | ❌ | |
| `.serverid` | Server ID | ❌ | |
| `.stats` | Bot stats | ❌ | |
| `.alias` | Aliases | ❌ | Use Red's Alias |
| `.calculate` | Calculator | ❌ | |
| `.config` | Config | ✅ | `[p]unicornia config` (Partial) |
| `.ga start` | Giveaway | ❌ | |
| `.serverinfo` | Server info | ❌ | Use Red's Core |
| `.userinfo` | User info | ❌ | Use Red's Core |
| `.quote*` | Quotes | ❌ | |
| `.remind` | Reminders | ❌ | |
| `.repeat` | Repeaters | ❌ | |
| `.todo` | Todo list | ❌ | |
| `.convert` | Converter | ❌ | |

## 11. Xp Module

| Nadeko Alias | Description | Unicornia Status | Notes |
| :--- | :--- | :---: | :--- |
| `.experience` | XP Check | ✅ | `[p]level check` |
| `.xpnotify` | XP Notify | ❌ | Server setting only |
| `.xpexclude` | XP Exclude | ⚠️ | `[p]unicornia guild excludechannel` |
| `.xpexclusionlist`| List excluded | ❌ | |
| `.xpleaderboard` | XP LB | ✅ | `[p]level leaderboard` |
| `.xpgleaderboard` | Global XP LB | ❌ | |
| `.xpadd` | Add XP | ❌ | |
| `.xptempreload` | Reload template | ❌ | |
| `.xpreset` | Reset XP | ❌ | |
| `.xpshop` | XP Shop | ✅ | `[p]xpshop` (Backgrounds) |
| `.xpshopbuy` | Buy XP item | ✅ | `[p]xpshop buy` |
| `.xpshopuse` | Use XP item | ✅ | `[p]xpshop use` |
| `.clubcreate` | Create club | ✅ | `[p]club create` |
| `.clubicon` | Club icon | ✅ | `[p]club icon` |
| `.clubinfo` | Club info | ✅ | `[p]club info` |
| `.clubbans` | Club bans | ❌ | |
| `.clubapps` | Club apps | ❌ | |
| `.clubapply` | Apply to club | ✅ | `[p]club apply` |
| `.clubaccept` | Accept member | ✅ | `[p]club accept` |
| `.clubreject` | Reject member | ✅ | `[p]club reject` |
| `.clubleave` | Leave club | ✅ | `[p]club leave` |
| `.clubkick` | Kick member | ✅ | `[p]club kick` |
| `.clubban` | Ban member | ✅ | `[p]club ban` |
| `.clubunban` | Unban member | ✅ | `[p]club unban` |
| `.clubdesc` | Club desc | ✅ | `[p]club desc` |
| `.clubdisband` | Disband club | ✅ | `[p]club disband` |
| `.clublb` | Club LB | ✅ | `[p]club leaderboard` |
| `.clubrename` | Rename club | ✅ | `[p]club rename` |
| `.clubtransfer` | Transfer club | ✅ | `[p]club transfer` |
| `.clubadmin` | Club admin | ✅ | `[p]club admin` |
| `.xprewsreset` | Reset rewards | ❌ | |
| `.xplvluprewards` | List rewards | ❌ | |
| `.xprolereward` | Role reward | ✅ | `[p]unicornia guild rolereward` |
| `.xpcurreward` | Currency reward | ✅ | `[p]unicornia guild currencyreward` |
