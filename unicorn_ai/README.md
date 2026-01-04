# UnicornAI

**UnicornAI** is an advanced Red Discord Bot cog that integrates with Google Vertex AI (Gemini) to provide an autonomous, persona-based AI assistant. It can automatically engage in conversations, maintaining a consistent personality and memory of recent chat history.

## Features
- **Vertex AI Integration**: Uses `gemini-3-pro-preview` (configurable) via asynchronous Google Cloud API calls.
- **Custom Personas**: Load character definitions from simple JSON files.
- **Context Awareness**: Remembers the last 50-100 messages in the channel.
- **Multi-Channel Support**: Configure different personas and intervals for different channels.
- **Auto-Messaging**: Configurable loop to make the AI speak periodically.
- **Smart Logic**: Automatically strips internal "thinking" tags (`<think>`) from model output.

## Installation

1.  **Dependencies**
    Ensure your bot's environment has the required libraries:
    ```bash
    pip install google-auth aiohttp
    ```

2.  **Service Account**
    - Create a Service Account in your Google Cloud Project with **Vertex AI User** permissions.
    - Download the JSON key file.
    - Rename it to `service_account.json` (or any `.json` name).
    - Place it inside the cog folder: `.../cogs/unicorn_ai/`.

3.  **Load the Cog**
    ```
    [p]load unicorn_ai
    ```

## Setup

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

## Configuration Commands
*All commands are restricted to the Bot Owner.*

- `[p]ai interval <seconds>`: Set how often the bot speaks **in the current channel** (default: 300s).
- `[p]ai history <limit>`: Set how many past messages the bot reads (Global setting, default: 50).
- `[p]ai model <name>`: Change the Gemini model version (Global setting).
- `[p]ai trigger [persona_name]`: Manually force the bot to generate a response immediately. Optionally provide a persona name to test it without loading it.

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
