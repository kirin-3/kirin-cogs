# Dashboard

Dashboard serves two Unicornia web sites from inside the bot. Both listen on loopback only; Caddy exposes them through
Cloudflare. They share the login code but keep separate sessions and cookies.

- **Staff site**, `staff.unicornia.net` on `127.0.0.1:8011`. Lists the ban records kept by the BanLog cog and the
  messages each banned member posted in the week before their ban, and manages the AutoMod cog's rulesets, rules and
  word lists, including its action log and the dry-run switch. Its Unicornia pages show, read-only, any member's
  economy and XP, the house economy, the cog's configuration and the stock market. Its Modmail pages show every
  thread the modmail bot has kept since October 2020, read-only. Its Gif votes page lists the thumbs-up and thumbs-down
  totals of every roleplay gif that has a vote.
- **Member site**, `my.unicornia.net` on `127.0.0.1:8012`. Every member can see their Unicornia profile, stocks, club,
  waifu standing and unicorn stable, buy and equip rank-card backgrounds, see the XP leaderboard and their own
  warnings, and turn
  their roleplay settings (Selective, Public, Servant and Untracked) on or off and see their roleplay stats and the busiest
  pairs, and turn the bot's daddy replies and the UnicornAI opt-out on or off. They can also browse the roleplay
  gifs and give each a thumbs up or down. Supporters also manage their custom commands, custom emojis and, if they
  were given one with `[p]assignrole`, their custom role. Supporters and Level 90+ members can send in a gif.

## Who can log in

Login is Discord OAuth2 with the `identify` scope.

The **staff site** creates a session only when all of these hold:

- the Discord account has two-factor authentication turned on;
- the user is a member of Unicornia (`684360255798509578`);
- the member holds the staff role (`696020813299580940`) or the Ban Members permission, the same gate as `[p]ban`.

Editing AutoMod (every POST that changes rulesets, rules, lists, or the dry-run switch) also requires a **bot owner**.
Staff accounts can view the automod pages but not change them.

The **member site** admits any member of Unicornia, with or without 2FA. What it shows depends on the member's roles
at the time of each request:

| Section | Who sees it |
| --- | --- |
| Profile, Backgrounds, Stocks, Club, Waifu, Leaderboard | Everyone, while the Unicornia cog is loaded |
| Warnings | Everyone, while the Moderation cog is loaded |
| Roleplay, Settings | Everyone |
| Gifs | Everyone, while the Roleplay cog is loaded. The page to send in a gif: the active supporter role (`700121551483437128`), the inactive one (`1458440559713718466`) or the Level 90+ role (`721360680770469958`) |
| Custom commands | The active supporter role (`700121551483437128`), or the inactive one (`1458440559713718466`) while the member still has commands |
| Custom emojis | A supporter role who can create emojis (the `[p]ce setrole` role), or who still has emojis |
| Custom role | Either supporter role, plus a role assigned with `[p]assignrole` |

The pages follow the same rules as the bot's commands, because they call the same cog methods. Only active supporters
can create custom commands, or edit them on the site (a replace in one step, under the create rules). Creating and renaming emojis needs the role set with `[p]ce setrole`. Either kind of
supporter can delete their own items. The per-member cooldowns count commands and site together. The member site can
only upload new emojis, not copy existing ones, and it can't add people to or remove them from the roleplay lists.

## Settings page

`/settings` on the member site has one section per cog, from a fixed list:

- **Auto-replies** (Responder): daddy replies, the same switch as `[p]daddyoptout`.
- **UnicornAI**: "Let the AI read my messages", the inverse of `[p]aioptout`. Turning it back on deletes the stored
  opt-out, so opted-in members have no record.

A section whose cog isn't loaded shows a notice, and changes to it get 503; the other section keeps working. A POST
names the section, key and new state; anything unknown gets 400.

## Gifs pages

`/gifs` on the member site lists the Roleplay cog's actions with the number of gifs each has. `/gifs/{action}` shows one
action's **Default** pool (untagged, `mlw` and `wlm` gifs, the ones the bot picks from when no pairing is asked for),
and `/gifs/{action}/wlw` and `/gifs/{action}/mlm` the other two, 5 gifs a page by file name (`?page=N`, clamped to the
last page). Each pool's tab shows how many gifs it has. A pool with more than one page has a pager above and below the
gifs: Previous and Next, and the numbers of the first, last and neighbouring pages (narrow screens show "Page 2 of 7"
in their place). The pages read the images folder each time, so a file change shows on the next load. Gifs are served by
`/gifs/{action}/file/{name}`, which only serves a name found in that action's folder (the cog looks it up in the
folder's listing; the name is never joined onto a path), and a browser may keep them for a day, privately. Members
aren't shown file names (only staff are, on the Gif votes page), and a gif with `eros` in its file name gets a small AI
badge; the Roleplay cog decides which, so the image address and the vote form still carry the name.

- **Voting.** Each gif has a thumbs up and a thumbs down. Each is a plain form (`POST /gifs/vote`) that saves the vote
  and returns to the same page and gif; pressing the thumb you chose takes the vote back. With scripts, `site.js`
  sends the same form with `fetch` and flips the buttons, so the gifs keep playing. Members only ever see their own
  vote, never totals. The return address is rebuilt from a pool name, a page number and a slot number that are checked
  first, never taken from the request.
- **Sending in a gif.** Members who may (see the table above) get a "Send in a gif" button on the Gifs pages. It opens
  `/gifs/upload`, a page of its own with a form for an action and a file; opened from an action's page
  (`/gifs/upload?action=bite`), it starts on that action. Anyone else gets 403 there. The Roleplay cog checks the
  upload (`POST /gifs/upload`): the file is a GIF by content, fits the review server's upload limit, and the member
  hasn't sent one in the last minute. It posts the gif in its review channel and keeps nothing; the site adds no size
  limit below the request limit under Protections. A sent gif returns to the upload page with a thank-you note; a
  refusal shows its message there and answers 400.
- **Staff.** `/gifs` on the staff site lists every gif with at least one vote and a file that still exists, lowest score
  first, 10 a page (`?page=N`, with the same pager), with its thumbs-up and thumbs-down totals. GET-only.
  `/gifs/{action}/file/{name}` shows the gif to staff and is never cached.

The pages answer 503 while the Roleplay cog isn't loaded.

## Warnings page

`/me/warnings` lists the member's own warnings in Unicornia, newest first, with the date, reason and points, and their
count and total. It never shows who gave a warning: the moderator field is left out, and so is the
`(YAGPDB, <date>, by <moderator>)` suffix on imported warnings. Mutes and other moderation records aren't shown. Every
member sees the page, "No warnings" included, while the Moderation cog is loaded; otherwise it answers 503. When
Unicornia isn't loaded, the top bar's Profile link goes here instead of `/me`.

## Unicornia pages

On the member site, where every `/me` page has a tab bar (Profile · Backgrounds · Stocks · Club · Waifu · Stable ·
Warnings):

- `/me`: wallet, bank, level and progress, rank, club, the equipped background (animated) and the last 20
  transactions. Only the member's own.
- `/me/backgrounds`: every buyable background, plus hidden ones the member owns. Buying asks for confirmation with the
  name and price; the purchase itself follows `xpshop buy`'s rules and charges at most once. Equipping follows
  `xpshop use`.
- `/me/stocks`: holdings with value and profit or loss, totals computed as `stock portfolio` does, and every dividend
  payout, newest first.
- `/me/club`: the member's club with its XP, rank, owner and every member (owner and admins marked), or their club
  invitations. Icons and banners are loaded only from `https://cdn.discordapp.com` or `https://unicornia.net`, the
  hosts the Content-Security-Policy already allows; any other URL is a `noreferrer` link, and non-web URLs are dropped.
- `/me/waifu`: what `waifu info` shows (price, owner, affinity, affinity from, waifus, gifts), without its list limits.
- `/me/stable`: the member's own stable — the same card image `[p]stable` posts (served by `/me/stable/card.webp`,
  rendered by the cog and cached 30 s per member), the earnings and coin box numbers, the ascension count, the
  collection grouped by rarity with seasonal breeds after, and the perks active in the stable, plus a Collect button
  that follows the card's Collect rules and returns with the amount collected. Undiscovered breeds show as ??? and
  their art (`/me/stable/art/{breed}.webp`) is only served for breeds the member has discovered, so URL guessing
  can't spoil one. Hatching, upgrades, releases and ascension stay in Discord.
- `/leaderboard?page=N`: the guild's current members by XP, 25 a page, each with their background as a still that
  animates while the row is hovered or focused. The member's own row is highlighted, and their rank is always shown.
  Like `level leaderboard`, only the top 300 are ranked, and the ranking is rebuilt at most once a minute.

On the staff site, open to all staff and GET-only, so nothing there can change Unicornia data:

- `/unicornia/members?q=`: find a member by ID or part of a name. `/unicornia/members/{id}` shows balances, rakeback,
  level and rank, club, gambling stats, backgrounds, shop inventory and the last 100 transactions. It works by ID for
  people who have left.
- `/unicornia/economy`: the 25 richest members, and the RTP, yield pool and dividend figures from `yieldstats`.
- `/unicornia/config`: the settings, channels, level rewards and whitelists. Deleted channels and roles show their ID.
- `/unicornia/market`: listed stocks and prices.

These pages answer 503 while the Unicornia cog isn't loaded.

## Modmail pages

On the staff site, open to all staff and GET-only. The data comes from the modmail bot (a separate Node bot, pm2 app
`mail`) through its own SQLite database, `/home/kirin/modmail/db/data.sqlite`. The dashboard opens it read-only, never
changes modmail, and keeps no copy.

- `/modmail?q=`: threads newest first, 50 a page. The search box takes a user ID (17–20 digits), a thread number
  (`#4829` or `4829`), or any other text, which matches usernames and message text, ignoring case.
- `/modmail/{number}`: the conversation. Member messages sit on the left, replies to the member on the right with the
  staff member's real name and, for anonymous replies, the role name the member saw. Internal staff chat, bot
  commands and system lines are marked, edited replies show both versions, and deleted replies are marked.
- Ban pages list the banned member's modmail threads.

Attachments are Discord CDN links, and their signatures expire. When a thread is opened, the dashboard asks Discord
for freshly signed links (`POST /attachments/refresh-urls`, with the bot's token, 50 links a call) and keeps them in
memory until they expire. Images are shown inline, other files as links. Nothing is downloaded or stored; a link
Discord won't refresh is shown as its file name marked unavailable.

If the database is missing or can't be read, the pages say modmail logs are unavailable and the rest of the site keeps
working.

Modmail writes the database with a rollback journal and waits up to 1 s for a reader, and each page does one short
read. If modmail's log (`pm2 logs mail`) ever shows `SQLITE_BUSY` or "database is locked", switch the file to WAL:
stop the `mail` app, run `sqlite3 /home/kirin/modmail/db/data.sqlite "PRAGMA journal_mode=WAL;"`, and start it again.
It needs no change to modmail's code, but backups must then copy `data.sqlite-wal` too, or use `.backup`.

On both sites, whether the user may still use the site is re-checked against the bot's member cache on every request,
so losing the staff role, or leaving the server, ends access on the next click. Sessions live in memory, expire
12 hours after login, and end on logout or when the cog unloads or the bot restarts. Logging back in takes one click.

## Protections

- Every route needs a session unless it is one of `/login`, `/callback`, `/logged-out`, or a static file. The staff and
  member cookies (`__Host-staff`, `__Host-member`) and session stores are separate, so a session from one site is
  never accepted by the other.
- Every POST must carry the session's CSRF token. The member site accepts bodies up to 9 MB, for custom command files,
  and reads them only after the session check. The one exception is a gif upload (`POST /gifs/upload`) from a member
  who may send in gifs, which accepts up to 100 MB, Cloudflare's own limit; the real ceiling is what Discord lets the
  bot upload. Everyone else, and every other route, keeps 9 MB.
- Uploads are checked by their content, not their file name: emojis must be PNG, JPEG or GIF, role icons PNG or JPEG.
- Pages carry a strict Content-Security-Policy, `nosniff`, `no-referrer`, `DENY` framing, `noindex`, and `no-store`.
  Both sites may show images from `cdn.discordapp.com`: modmail attachments on the staff site; emojis, role icons and
  avatars on the member site. The member site may also show images from `unicornia.net`, for rank-card backgrounds. All user text is
  HTML-escaped by Jinja2.
- Fonts (Fredoka, Nunito and Caveat, the main site's, under the OFL in `static/fonts/OFL.txt`) load only from the
  site itself. They are the only public cache entries. Only the member site's images from the bot's own storage may be
  kept, and only by the member's own browser (`private`): the roleplay gifs (a day), the stable art (5 minutes) and the
  stable card (30 seconds). Everything else, pages and scripts included, is `no-store`.
- The only script is `static/site.js`. The policy allows the site's own files and nothing else: no inline scripts and no
  other hosts. On the member site the script may send requests to the site itself (`connect-src 'self'`), which is how
  a gif vote saves in place; on the staff site scripts can't make requests at all. It adds conveniences only, such as
  adding editor rows in place, a live preview of the custom role, animating leaderboard backgrounds, local times,
  filter boxes, delete confirmations, in-place gif votes, and blocking a second submit while a form is sending. Every
  page works without it, and every change is still checked by the server. It writes text and attributes into the page,
  never HTML.
- The login callbacks share one limit, because both sites log in through the bot's IP. Discord gets at most 5 code
  exchanges per minute per client IP and 30 per minute in total, and none at all while it is answering 429. Member
  logins stop at 20 a minute, so staff can always use the last 10.
- Cookies use the `__Host-` prefix, so they are never shared with other `unicornia.net` subdomains.

## Hardcoded values

| Setting | Staff site | Member site |
| --- | ---: | ---: |
| Listener | `127.0.0.1:8011` | `127.0.0.1:8012` |
| Redirect URI | `https://staff.unicornia.net/callback` | `https://my.unicornia.net/callback` |
| Access | Staff role `696020813299580940` or Ban Members, with 2FA | Any member |
| Logins per minute | 30, shared | 20 of the 30 |

Guild `684360255798509578`, supporter roles `700121551483437128` (active) and `1458440559713718466` (inactive), and a
session length of 12 hours apply to both.

Member site request limits: 9 MB, and 100 MB for a gif upload from a member who may send in gifs. Who may send in a gif
(the two supporter roles and Level 90+ `721360680770469958`), the review channel `1554813851302887494` and the 60 second
wait between gifs live in the Roleplay cog, `roleplay/const.py`.

## Deployment checklist

1. Cloudflare, `unicornia.net` zone:
   - proxied (orange cloud) `A` records `staff` and `my` → `46.225.188.59`. The VPS only accepts web traffic from
     Cloudflare, so an unproxied record will not load;
   - SSL/TLS mode **Full (strict)**. Flexible makes Caddy redirect in a loop;
   - a rate-limiting rule for requests to `staff.unicornia.net` and `my.unicornia.net` with path `/login` or
     `/callback`.
2. Discord Developer Portal, the bot's application, OAuth2: add the redirects `https://staff.unicornia.net/callback`
   and `https://my.unicornia.net/callback`. Copy the client secret and store it in the bot:

   ```
   [p]set api dashboard client_secret,<secret>
   ```

3. VPS: add these blocks to `/etc/caddy/Caddyfile`, then run `caddy validate` and reload Caddy:

   ```
   staff.unicornia.net {
       reverse_proxy 127.0.0.1:8011
   }

   my.unicornia.net {
       reverse_proxy 127.0.0.1:8012
   }
   ```

4. Load the cogs: `[p]load banlog automod dashboard`, and have `customcommand`, `customemoji`, `customrolecolor`,
   `responder`, `roleplay` and `unicornia` loaded. Pages whose cog is not loaded show a notice instead.
   Give the bot View Channel, Send Messages and Attach Files in the gif review channel `1554813851302887494`, or gif
   uploads answer that they are unavailable.
5. Check that:
   - a staff account with 2FA can log in to the staff site, and a non-staff account gets "Staff only";
   - a member without 2FA can log in to the member site and sees only Roleplay and Settings;
   - an inactive supporter can list and delete their items but has no create forms;
   - an active supporter can create a command and an emoji;
   - a supporter with an assigned role can recolor it;
   - `/gifs` lists 30 actions, and a thumbs up on a gif is still there after a reload;
   - a gif sent in by a Level 90+ account arrives in the review channel without pinging them;
   - the staff site's Gif votes page lists the gif that was voted on.

To roll back, run `[p]unload dashboard` and remove the Caddy blocks.
