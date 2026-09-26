# Dashboard

Dashboard serves two Unicornia web sites from inside the bot. Both listen on loopback only; Caddy exposes them through
Cloudflare. They share the login code but keep separate sessions and cookies.

- **Staff site**, `staff.unicornia.net` on `127.0.0.1:8011`. Lists the ban records kept by the BanLog cog and the
  messages each banned member posted in the week before their ban, and manages the AutoMod cog's rulesets, rules and
  word lists, including its action log and the dry-run switch.
- **Member site**, `my.unicornia.net` on `127.0.0.1:8012`. Every member can see their roleplay settings and turn
  Selective, Public and Servant on or off. Supporters also manage their custom commands, custom emojis and, if they
  were given one with `[p]assignrole`, their custom role.

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
| Roleplay | Everyone |
| Custom commands | The active supporter role (`700121551483437128`), or the inactive one (`1458440559713718466`) while the member still has commands |
| Custom emojis | A supporter role who can create emojis (the `[p]ce setrole` role), or who still has emojis |
| Custom role | Either supporter role, plus a role assigned with `[p]assignrole` |

The pages follow the same rules as the bot's commands, because they call the same cog methods. Only active supporters
can create custom commands, or edit them on the site (a replace in one step, under the create rules). Creating and renaming emojis needs the role set with `[p]ce setrole`. Either kind of
supporter can delete their own items. The per-member cooldowns count commands and site together. The member site can
only upload new emojis, not copy existing ones, and it can't add people to or remove them from the roleplay lists.

On both sites, whether the user may still use the site is re-checked against the bot's member cache on every request,
so losing the staff role, or leaving the server, ends access on the next click. Sessions live in memory, expire
12 hours after login, and end on logout or when the cog unloads or the bot restarts. Logging back in takes one click.

## Protections

- Every route needs a session unless it is one of `/login`, `/callback`, `/logged-out`, or a static file. The staff and
  member cookies (`__Host-staff`, `__Host-member`) and session stores are separate, so a session from one site is
  never accepted by the other.
- Every POST must carry the session's CSRF token. The member site accepts bodies up to 9 MB, for custom command files,
  and reads them only after the session check.
- Uploads are checked by their content, not their file name: emojis must be PNG, JPEG or GIF, role icons PNG or JPEG.
- Pages carry a strict Content-Security-Policy, `nosniff`, `no-referrer`, `DENY` framing, `noindex`, and `no-store`.
  The member site may also show images from `cdn.discordapp.com`, for emojis and role icons. All user text is
  HTML-escaped by Jinja2.
- The only script is `static/site.js`. The policy allows the site's own files and nothing else: no inline scripts, no
  other hosts, and no requests from scripts. It adds conveniences only, such as adding editor rows in place, a live
  preview of the custom role, local times, filter boxes, and delete confirmations. Every page works without it, and
  every change is still checked by the server. It writes text into the page, never HTML.
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

4. Load the cogs: `[p]load banlog automod dashboard`, and have `customcommand`, `customemoji`, `customrolecolor` and
   `roleplay` loaded. Pages whose cog is not loaded show a notice instead.
5. Check that:
   - a staff account with 2FA can log in to the staff site, and a non-staff account gets "Staff only";
   - a member without 2FA can log in to the member site and sees only Roleplay;
   - an inactive supporter can list and delete their items but has no create forms;
   - an active supporter can create a command and an emoji;
   - a supporter with an assigned role can recolor it.

To roll back, run `[p]unload dashboard` and remove the Caddy blocks.
