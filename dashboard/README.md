# Dashboard

Dashboard serves Unicornia's staff web site, `staff.unicornia.net`, from inside the bot. It listens on
`127.0.0.1:8011` only; Caddy exposes it through Cloudflare. Its first pages list the ban records kept by the BanLog cog
and show the messages each banned member posted in the week before their ban.

## Who can log in

Login is Discord OAuth2 with the `identify` scope. A session is created only when all of these hold:

- the Discord account has two-factor authentication turned on;
- the user is a member of Unicornia (`684360255798509578`);
- the member holds the staff role (`696020813299580940`) or the Ban Members permission, the same gate as `[p]ban`.

Staff status is re-checked against the bot's member cache on every request, so removing the role ends access on the
next click. Sessions live in memory, expire 12 hours after login, and end on logout or when the cog unloads or the bot
restarts. Logging back in takes one click.

## Protections

- Every route needs a staff session unless it is one of `/login`, `/callback`, `/logged-out`, or a static file.
- Every POST must carry the session's CSRF token.
- Pages carry a strict Content-Security-Policy (no scripts), `nosniff`, `no-referrer`, `DENY` framing, `noindex`, and
  `no-store`. All user text is HTML-escaped by Jinja2.
- The login callback sends Discord at most 5 code exchanges per minute per client IP and 30 per minute in total, and
  none at all while Discord is answering 429. This keeps a login flood from getting the bot's shared IP blocked.
- Cookies use the `__Host-` prefix, so they are never shared with other `unicornia.net` subdomains.

## Hardcoded values

| Setting | Value |
| --- | ---: |
| Guild | `684360255798509578` |
| Staff role | `696020813299580940` |
| Listener | `127.0.0.1:8011` |
| Redirect URI | `https://staff.unicornia.net/callback` |
| Session length | 12 hours |

## Deployment checklist

1. Cloudflare, `unicornia.net` zone:
   - a proxied (orange cloud) `A` record `staff` → `46.225.188.59`. The VPS only accepts web traffic from Cloudflare, so
     an unproxied record will not load;
   - SSL/TLS mode **Full (strict)**. Flexible makes Caddy redirect in a loop;
   - one rate-limiting rule for requests to `staff.unicornia.net` with path `/login` or `/callback`.
2. Discord Developer Portal, the bot's application, OAuth2: add the redirect `https://staff.unicornia.net/callback`.
   Copy the client secret and store it in the bot:

   ```
   [p]set api dashboard client_secret,<secret>
   ```

3. VPS: add this block to `/etc/caddy/Caddyfile`, then run `caddy validate` and reload Caddy:

   ```
   staff.unicornia.net {
       reverse_proxy 127.0.0.1:8011
   }
   ```

4. Load the cogs: `[p]load banlog dashboard`.
5. Check that a staff account with 2FA can log in, a non-staff account gets "Staff only", and a test ban with message
   deletion shows the purged messages.

To roll back, run `[p]unload dashboard banlog` and remove the Caddy block.
