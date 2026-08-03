# UnicornAI

**UnicornAI** is an advanced Red Discord Bot cog that integrates with Google Vertex AI and OpenAI-compatible endpoints (NanoGPT, OpenRouter, etc.) to provide an autonomous, persona-based AI assistant. It can automatically engage in conversations, maintaining a consistent personality and memory of recent chat history.

The bot uses webhooks to impersonate personas, posting messages that appear to come from the character itself.

## Features
- **Multiple Provider Support**: Switch between Google Vertex AI and OpenAI-compatible endpoints.
- **Vertex AI Integration**: Uses `gemini-3-pro-preview` (configurable) via asynchronous Google Cloud API calls.
- **OpenAI-Compatible Support**: Works with NanoGPT, OpenRouter, and other OpenAI-compatible APIs.
- **Custom Personas**: Load character definitions from simple JSON files.
- **Context Awareness**: Remembers the last 50-100 messages in the channel (configurable per persona or globally).
- **Multi-Channel Support**: Configure different personas and intervals for different channels.
- **Thread Support**: Works in both text channels and threads.
- **Auto-Messaging**: Configurable loop to make the AI speak periodically.
- **Webhook Impersonation**: Uses webhooks to post messages as the persona character.
- **User Opt-Out**: Users can opt out of having their messages included in AI context.
- **Smart Logic**: Automatically strips internal "thinking" tags (`<thinking>`) from model output.

## Installation

1.  **Dependencies**
    Ensure your bot's environment has the required libraries:
    ```bash
    pip install google-auth aiohttp
    ```

2.  **Service Account (for Vertex AI)**
    - Create a Service Account in your Google Cloud Project with **Vertex AI User** permissions.
    - Download the JSON key file.
    - Rename it to `service_account.json` (or any `.json` name).
    - Place it inside the cog folder: `.../cogs/unicorn_ai/`.

3.  **Load the Cog**
    ```
    [p]load unicorn_ai
    ```

## Setup

### Using Vertex AI (Default)

1.  **Initialize Credentials**
    ```
    [p]ai setup
    ```
    *If successful, the bot will confirm credentials loaded.*

2.  **Configure a Channel**
    Go to the channel you want the bot to speak in.

3.  **Load a Persona (Per Channel)**
    List available personas:
    ```
    [p]ai persona list
    ```
    Load one for the current channel:
    ```
    [p]ai persona load example
    ```

4.  **Start the Bot (Per Channel)**
    ```
    [p]ai toggle
    ```

### Using OpenAI-Compatible Endpoints (NanoGPT, OpenRouter, etc.)

1.  **Set API Key**
    ```
    [p]ai openai_key your_api_key_here
    ```
    *Note: This command is provided as an alternative to `[p]set api openai` which may have issues in some Redbot versions.*

2.  **Switch Provider**
    ```
    [p]ai provider openai
    ```

3.  **Configure Model (Optional)**
    The default model is `zai-org/glm-5:thinking` with temperature 0.95, top_k 40, and top_p 0.93.
    To change the model:
    ```
    [p]ai openai_model your_model_name
    ```

4.  **Configure Channel**
    Follow the same steps as Vertex AI (load persona, toggle, etc.).

## Permissions Required
- **Manage Webhooks**: Required for the bot to impersonate personas via webhooks. If not granted, the bot will fall back to posting messages as itself.

## Configuration Commands
*All commands are restricted to the Bot Owner.*

### General Settings
- `[p]ai interval <seconds>`: Set how often the bot speaks **in the current channel** (default: 300s).
- `[p]ai history <limit>`: Set how many past messages the bot reads (Global setting, default: 50).
- `[p]ai trigger [persona_name]`: Manually force the bot to generate a response immediately. Optionally provide a persona name to test it without loading it.
- `[p]ai toggle`: Enable or disable the auto-messaging loop for the current channel.
- `[p]ai setup`: Reload Vertex AI credentials from the `service_account.json` file.

### Provider Settings
- `[p]ai provider <vertex|openai>`: Switch between Vertex AI and OpenAI-compatible endpoints.
- `[p]ai model <name>`: Set the Vertex AI model name (e.g., `gemini-3-pro-preview`).
- `[p]ai openai_model <name>`: Set the OpenAI-compatible model name (e.g., `zai-org/glm-5:thinking`).
- `[p]ai openai_key <api_key>`: Set the OpenAI API key directly (alternative to `[p]set api openai`).

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

## OpenAI-Compatible Configuration

The OpenAI provider is pre-configured for NanoGPT with the following settings:
- **Endpoint**: `https://nano-gpt.com/api/v1/chat/completions`
- **Model**: `zai-org/glm-5:thinking`
- **Temperature**: 0.95
- **Top-K**: 40
- **Top-P**: 0.93
- **Max Tokens**: 8192

To use a different OpenAI-compatible provider (like OpenRouter), you can modify the `openai_endpoint` setting in the config or use a provider that accepts the same API format.

## Troubleshooting

### Bot not speaking automatically
- Ensure the channel has auto-messaging enabled: `[p]ai toggle`
- Check that a persona is loaded: `[p]ai persona list` then `[p]ai persona load <name>`
- Verify the interval is appropriate: `[p]ai interval <seconds>` (default is 300 seconds)

### "No active persona set" error
- Load a persona for the channel: `[p]ai persona load <persona_name>`

### OpenAI responses failing
- Ensure the API key is set: `[p]ai openai_key <your_key>` or `[p]set api openai <your_key>`
- Verify the provider is set to openai: `[p]ai provider openai`

### Vertex AI responses failing
- Ensure `service_account.json` is in the cog folder
- Run `[p]ai setup` to reload credentials
- Check the service account has "Vertex AI User" permissions

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
