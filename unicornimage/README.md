# UnicornImage

UnicornImage is a dual-backend text-to-image generation cog for Red Discord Bot. It leverages **Stable Horde** for free, accessible generation and **Modal** for high-speed, premium generation.

## Features

- **Free Generation**: Uses [Stable Horde](https://stablehorde.net/) (crowdsourced GPUs) to generate images. Slower but free for everyone.
- **Premium Generation**: Uses [Modal](https://modal.com/) (private serverless GPUs) for fast, high-quality generation. Restricted to users with a specific role.
- **Dual Backends**: Seamlessly switches between backends based on the command used.
- **Model Selection**: Choose between different base models (e.g., SDXL, Pony) for premium generations.
- **LoRA Support**: Easily apply style presets (LoRAs) compatible with the selected model.
- **SFW Enforcement**: Free generations are strictly SFW. Premium generations are unfiltered (Modal backend).

## Requirements

1.  **Dependencies**:
    - `modal` (Python package)
    - `aiohttp` (Included in Red)
2.  **External Services**:
    - A [Stable Horde](https://stablehorde.net/) API Key (Optional, works without but slower).
    - A [Modal](https://modal.com/) account (Required for Premium features).

## Setup Guide

### 1. Installation
Ensure `modal` is installed in your bot's environment:
```bash
pip install modal
```
Load the cog:
```
[p]load unicornimage
```

### 2. Modal Setup (Premium)
1.  Create a Modal account.
2.  Authenticate your bot's host machine with Modal:
    ```bash
    modal setup
    ```
3.  Deploy the included Modal app (located in `modal_app/`):
    ```bash
    cd /path/to/cogs/unicornimage/modal_app
    modal deploy text2image.py
    ```
4.  Configure the app name in the bot (default is `text2image`):
    ```
    [p]unicornimage setapp text2image
    ```

### 3. Configuration
- **Set Horde API Key** (Optional):
  ```
  [p]unicornimage setapi YOUR_API_KEY
  ```
- **Set Premium Role** (Required for `[p]gen`):
  ```
  [p]unicornimage setrole @Supporter
  ```
- **Set Default Prompt** (Optional, appended to Modal requests):
  ```
  [p]unicornimage setprompt high quality, masterpiece
  ```

## Usage

### User Commands
- `[p]genfree <prompt> [style] [negative_prompt]`: Generate an image using Stable Horde (Free).
- `[p]gen <prompt> [model] [style] [negative_prompt]`: Generate an image using Modal (Premium).
  - **Note**: When using text commands, use quotes for the prompt: `[p]gen "a cat" standard anime`
- `[p]loras`: List available style presets.

### Models & Styles
- **Models**: You can choose between models like `standard` (SDXL) or `pony` (Pony V6).
- **Styles**: Apply LoRAs using the `style` parameter. Ensure the style is compatible with the selected model (e.g., Pony styles for Pony model).

## Troubleshooting
- **Modal Error**: If `[p]gen` fails with an authentication error, ensure the bot's host machine has run `modal setup` or has `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` environment variables set.
- **Horde Error**: If `[p]genfree` is slow, get an API key from Stable Horde to increase priority.
