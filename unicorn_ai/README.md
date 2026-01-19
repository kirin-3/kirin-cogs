# UnicornAI

**UnicornAI** is an advanced Red Discord Bot cog that integrates with Google Vertex AI and OpenAI-compatible endpoints (NanoGPT, OpenRouter, etc.) to provide an autonomous, persona-based AI assistant. It can automatically engage in conversations, maintaining a consistent personality and memory of recent chat history.

## Features
- **Multiple Provider Support**: Switch between Google Vertex AI and OpenAI-compatible endpoints.
- **Vertex AI Integration**: Uses `gemini-3-pro-preview` (configurable) via asynchronous Google Cloud API calls.
- **OpenAI-Compatible Support**: Works with NanoGPT, OpenRouter, and other OpenAI-compatible APIs.
- **Custom Personas**: Load character definitions from simple JSON files.
- **Context Awareness**: Remembers the last 50-100 messages in the channel.
- **Multi-Channel Support**: Configure different personas and intervals for different channels.
- **Auto-Messaging**: Configurable loop to make the AI speak periodically.
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
    [p]set api openai your_api_key_here
    ```

2.  **Switch Provider**
    ```
    [p]ai provider openai
    ```

3.  **Configure Model (Optional)**
    The default model is `zai-org/glm-4.7:thinking` with temperature 0.95, top_k 40, and top_p 0.93.
    To change the model:
    ```
    [p]ai openai_model your_model_name
    ```

4.  **Configure Channel**
    Follow the same steps as Vertex AI (load persona, toggle, etc.).

## Configuration Commands
*All commands are restricted to the Bot Owner.*

### General Settings
- `[p]ai interval <seconds>`: Set how often the bot speaks **in the current channel** (default: 300s).
- `[p]ai history <limit>`: Set how many past messages the bot reads (Global setting, default: 50).
- `[p]ai trigger [persona_name]`: Manually force the bot to generate a response immediately. Optionally provide a persona name to test it without loading it.

### Provider Settings
- `[p]ai provider <vertex|openai>`: Switch between Vertex AI and OpenAI-compatible endpoints.
- `[p]ai model <name>`: Set the Vertex AI model name (e.g., `gemini-3-pro-preview`).
- `[p]ai openai_model <name>`: Set the OpenAI-compatible model name (e.g., `zai-org/glm-4.7:thinking`).

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
    "after_context": "[System Note: Be brief.]",
    "first_message": "Hello! *neigh*",
    "examples": []
}
```

- **system_prompt**: The core instruction sent to the AI.
- **after_context**: Text appended to the *end* of the conversation history (useful for reminders like "Keep it short").
- **allow_summon**: If set to `true`, users can summon this persona with the `[p]summon` command (with cooldowns).

## OpenAI-Compatible Configuration

The OpenAI provider is pre-configured for NanoGPT with the following settings:
- **Endpoint**: `https://nano-gpt.com/api/v1/chat/completions`
- **Model**: `zai-org/glm-4.7:thinking`
- **Temperature**: 0.95
- **Top-K**: 40
- **Top-P**: 0.93
- **Max Tokens**: 8192

To use a different OpenAI-compatible provider (like OpenRouter), you can modify the `openai_endpoint` setting in the config or use a provider that accepts the same API format.

## User Commands

- `[p]summon <persona_name>`: Summon a specific persona to chat (subject to cooldowns).
- `[p]aioptout`: Toggle your opt-out status for the AI. If opted out, your messages will not be included in the AI context.
