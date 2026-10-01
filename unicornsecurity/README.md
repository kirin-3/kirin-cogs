# UnicornSecurity (Spoilered Image Filter)

A single-purpose channel filter: monitors one configurable channel per guild and deletes any message containing an unspoilered non-Tenor image link or image attachment, warning the author for 10 seconds. **Edited messages are filtered too** — editing a message to add an image link removes it the same way (link-preview embed updates alone don't).

## How Detection Works

- `tenor.com` links are always allowed.
- Links inside `||spoiler||` tags and attachments marked as spoiler are always allowed.
- Uploads count as images by their content type (or, without one, their filename). Other files, such as text and video, are left alone.
- Other URLs are matched against regex patterns for common image hosts (file extensions like png/jpg/gif/webp, imgur, giphy, redd.it, gfycat).
- If no pattern matches, the bot performs a HEAD request to check whether the URL serves `image/*` content, so image links without a file extension are caught too.

## Commands

All commands require **Administrator** permission. Prefix-only.

| Command | Description |
|---------|-------------|
| `[p]imagefilter status` | Show the current status of the image filter. |
| `[p]imagefilter setchannel [channel]` | Set the filtered channel (defaults to the current channel). |

## Setup

1. Load the cog: `[p]load unicornsecurity`
2. Set the filtered channel: `[p]imagefilter setchannel #gif-channel`. A default channel (`1319688029530492948`) is configured out of the box; on any other server the filter does nothing until you set a channel.
3. Ensure the bot can **Manage Messages** and **Send Messages** in that channel. Members need **Embed Links** for spoilered links and **Attach Files** for spoilered uploads.

## Data Storage

One guild-scoped channel ID. No user data is stored.
