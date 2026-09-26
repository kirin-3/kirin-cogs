# Unicornia XP Shop System

The XP Shop allows users to purchase and equip custom backgrounds for their XP cards (`[p]level check`).

## Configuration

The shop is configured via the `xp_config.yml` file located in the `unicornia` cog directory.

### Adding Backgrounds

To add a new background, edit `xp_config.yml` and add an entry under `shop.bgs`.

**Format:**
```yaml
shop:
  isEnabled: true
  bgs:
    unique_key_name:
      name: "Display Name"
      price: 10000
      url: "https://unicornia.net/images/example.gif"
      preview: "https://unicornia.net/images/example.webp"
      still: "https://unicornia.net/images/example-still.webp"
      desc: "Optional description"
      hidden: false # Set to true to hide from shop
```

- **unique_key_name**: A unique identifier for the background (no spaces).
- **name**: The name shown to users.
- **price**: Cost in Slut points. Set to 0 for free.
- **url**: Direct link to the image (PNG, JPG, or GIF). Rank cards always use this one.
- **preview**, **still**: (Optional) Lighter versions for the member site: an animated WebP, and its first frame. The
  site shows `preview` (or `url`) where it animates a background, and `still` (or `preview`, or `url`) on the
  leaderboard until a row is hovered. Leave them out and the site uses `url`.
- **desc**: A short description shown in the shop.
- **hidden**: (Optional) If `true`, the background will not appear in the public shop list (`[p]xpshop backgrounds`) and cannot be purchased. It can still be assigned by the bot owner.

### Making the WebP versions

The images are served by the Astro site (`unicornia-astro/public/images/`). From this repo, with the Red environment:

```
redenv/Scripts/python.exe unicornia/tools/bg_webp.py ../unicornia-astro/public/images/example.gif
```

It writes `example.webp` (animated, 480 px wide, quality 70) and `example-still.webp` next to the GIF, and prints the
`preview` and `still` lines to paste. Deploy the Astro site before the config that points at the new files.

### Reloading Configuration

After editing `xp_config.yml`, run the following command to apply changes without restarting the bot:

```
[p]xpshop reload
```

## Commands

### User Commands
- `[p]xpshop backgrounds` (Aliases: `bg`, `bgs`): View and buy available backgrounds.
- `[p]xpshop buy <key>`: Purchase a specific background.
- `[p]xpshop use <key>`: Equip a purchased background.
- `[p]xpshop owned` (Aliases: `inventory`, `inv`): View your inventory of owned backgrounds.
- `[p]xpshopbuy <type> [key]`: Shortcut to buy XP shop items (e.g., `[p]xpshopbuy bg default`).

Members can also buy and equip backgrounds on the member site, `my.unicornia.net/me/backgrounds`, after a confirmation
prompt. The site and the commands use the same rules (`buy_background` and `use_background` on the cog), so the same
refusals apply, and a background is only ever charged for once, however many times the button or command is used.

### Owner Commands
- `[p]xpshop give <user> <key>`: Give a background to a user for free (bypasses price and hidden status).
- `[p]xpshop reload`: Reload the configuration file.

## Hidden Backgrounds

You can create exclusive backgrounds that are not available for purchase by setting `hidden: true` in the config. These can be used for:
- Event rewards
- Patreon perks
- Staff items

To give a hidden background to a user, use:
```
[p]xpshop give @User background_key
```
