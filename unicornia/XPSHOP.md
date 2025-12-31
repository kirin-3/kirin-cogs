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
      url: "https://example.com/image.png"
      desc: "Optional description"
      hidden: false # Set to true to hide from shop
```

- **unique_key_name**: A unique identifier for the background (no spaces).
- **name**: The name shown to users.
- **price**: Cost in Slut points. Set to 0 for free.
- **url**: Direct link to the image (PNG, JPG, or GIF).
- **desc**: A short description shown in the shop.
- **hidden**: (Optional) If `true`, the background will not appear in the public shop list (`[p]xpshop backgrounds`) and cannot be purchased. It can still be assigned by the bot owner.

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
- `[p]xpshop owned`: View your inventory of owned backgrounds.
- `[p]xpshopbuy <type> [key]`: Shortcut to buy XP shop items (e.g., `[p]xpshopbuy bg default`).

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
