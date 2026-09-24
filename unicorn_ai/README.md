# UnicornAI

**UnicornAI** is a Red Discord Bot cog that talks to OpenAI-compatible chat completion endpoints (**NanoGPT** by default, or OpenRouter, NVIDIA NIM, and others) to provide an autonomous, persona-based AI. It can join conversations on a timer, keeping a consistent personality and a memory of recent chat history.

The bot uses webhooks to impersonate personas, posting messages that appear to come from the character itself.

## Features
- **OpenAI-Compatible Endpoints**: NanoGPT out of the box; point it at any other compatible API with `[p]ai endpoint`.
- **Custom Personas**: Load character definitions from simple JSON files.
- **Context Awareness**: Remembers the last 50-100 messages in the channel (configurable per persona or globally). The persona's own earlier replies are recognised as its own, so it does not answer itself.
- **Multi-Channel Support**: Configure different personas and intervals for different channels.
- **Thread Support**: Works in both text channels and threads.
- **Auto-Messaging**: Configurable loop to make the AI speak periodically.
- **Webhook Impersonation**: Uses webhooks to post messages as the persona character.
- **User Opt-Out**: Users can opt out of having their messages included in AI context.
- **Safe Failures**: API errors are never posted in the channel. A failed scheduled run waits a full interval before retrying, and repeated failures back off (doubling up to 24 hours) until a run succeeds.
- **Reasoning Cleanup**: Inline `<think>` blocks (including ones cut off unclosed) are stripped from replies.

## Installation

1.  **Dependencies**
    ```bash
    pip install aiohttp
    ```

2.  **Load the Cog**
    ```
    [p]load unicorn_ai
    ```

## Setup

1.  **Set the API Key**
    ```
    [p]ai key your_api_key_here
    ```
    The key is stored as Red's `openai` API token (the same as `[p]set api openai api_key,<key>`), and the command message is deleted.

2.  **Endpoint and Model (Optional)**
    The defaults are NanoGPT (`https://nano-gpt.com/api/v1/chat/completions`) with the `zai-org/glm-5:thinking` model.
    ```
    [p]ai endpoint https://openrouter.ai/api/v1
    [p]ai model your_model_name
    ```

3.  **Load a Persona (Per Channel)**
    ```
    [p]ai persona list
    [p]ai persona load example
    ```

4.  **Start the Bot (Per Channel)**
    ```
    [p]ai toggle
    ```

## Permissions Required
- **Manage Webhooks**: Required for the bot to impersonate personas via webhooks. If not granted, the bot will fall back to posting messages as itself.

## Configuration Commands
*All commands are restricted to the Bot Owner.*

### General Settings
- `[p]ai interval <seconds>`: Set how often the bot speaks **in the current channel** (default: 300s).
- `[p]ai history <limit>`: Set how many past messages the bot reads (Global setting, default: 50).
- `[p]ai trigger [persona_name]`: Manually force the bot to generate a response immediately. Optionally provide a persona name to test it without loading it.
- `[p]ai toggle`: Enable or disable the auto-messaging loop for the current channel.

### Endpoint Settings
- `[p]ai endpoint [url]`: Set the OpenAI-compatible endpoint. A base URL like `https://nano-gpt.com/api/v1` gets `/chat/completions` added. Leave empty to reset to NanoGPT. (Alias: `openai_endpoint`)
- `[p]ai model <name>`: Set the model name sent to the endpoint. (Alias: `openai_model`)
- `[p]ai key <api_key>`: Set the API key. (Alias: `openai_key`)
- `[p]ai settings`: Show the endpoint, model, history limit, and whether a key is set.

### Persona Management
- `[p]ai persona list`: List available personas.
- `[p]ai persona load <name>`: Load a persona for the current channel.

## Persona JSON Structure

Create new JSON files in `.../unicorn_ai/data/personas/`.

```json
{
    "name": "Unicorn",
    "description": "Internal description for the admin.",
    "system_prompt": "You are a magical Unicorn. You end sentences with *neigh*.",
    "personality": "Cheerful, Energetic",
    "avatar_url": "https://example.com/unicorn.png",
    "after_context": "[System Note: Be brief.]",
    "history_limit": 100,
    "first_message": "Hello! *neigh*",
    "examples": [],
    "allow_summon": true
}
```

- **name**: The display name of the persona (used in webhooks).
- **description**: Internal description for admin reference.
- **system_prompt**: The core instruction sent to the AI defining the persona's behavior.
- **personality**: Brief description of personality traits.
- **avatar_url**: (Optional) URL to an image for the persona's webhook avatar.
- **after_context**: (Optional) Text appended to the *end* of the conversation history (useful for reminders like "Keep it short").
- **history_limit**: (Optional) Override the global history limit for this specific persona.
- **first_message**: (Optional) A greeting message the persona might use.
- **examples**: (Optional) Example conversations for few-shot learning.
- **allow_summon**: If set to `true`, users can summon this persona with the `[p]summon` command (subject to cooldowns).

## Request Settings

Every request uses:
- **Temperature**: 0.95
- **Top-K**: 40
- **Top-P**: 0.93
- **Max Tokens**: 8192
- **Timeout**: 180 seconds

## Troubleshooting

### Bot not speaking automatically
- Ensure the channel has auto-messaging enabled: `[p]ai toggle`
- Check that a persona is loaded: `[p]ai persona list` then `[p]ai persona load <name>`
- Verify the interval is appropriate: `[p]ai interval <seconds>` (default is 300 seconds)
- Check the bot logs: failed runs are logged with the time of the next attempt. After repeated failures the wait doubles each time (up to 24 hours); one successful run, such as `[p]ai trigger`, resets it.

### "No active persona set" error
- Load a persona for the channel: `[p]ai persona load <persona_name>`

### Responses failing
- Run `[p]ai trigger`: as the bot owner you will see the API error.
- Check `[p]ai settings` for the endpoint, model, and whether the key is set.

### Bot posting as itself instead of persona
- The bot needs "Manage Webhooks" permission to impersonate personas via webhooks
- Grant the permission or allow the bot to create webhooks in the channel

## User Commands

- `[p]summon <persona_name>`: Summon a specific persona to the current channel to chat immediately.
  - **Cooldowns**: 1 hour per user, 10 minutes per channel (bot owners bypass cooldowns).
  - Only personas with `allow_summon: true` in their JSON file can be summoned.
  - Supports autocomplete to show available summonable personas.
- `[p]aioptout`: Toggle your opt-out status for the AI. If opted out, your messages will not be included in the AI context.
  - Use `[p]aioptout` again to opt back in.

Only one AI request may be in flight per channel, with two generations globally by default. Overlapping scheduled/manual requests in the same channel are rejected, malformed interval/history values are bounded, and all model output is sent with mentions disabled.
