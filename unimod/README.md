# UniMod - AI-Powered Auto Moderation Cog

Intelligent auto-moderation system that combines **VADER sentiment analysis** for local pre-filtering with **GLM5 via NanoGPT** for accurate rule violation detection.

## Features

- **Two-Stage Filtering**: VADER sentiment analysis pre-filters messages before AI review, reducing API costs
- **AI-Powered Detection**: GLM5 model analyzes conversation context against server rules
- **Whitelist-Based Monitoring**: Only monitors channels you explicitly add
- **Anti-Censorship Design**: Explicitly permits 18+ content while detecting actual rule violations
- **Per-Channel Buffers**: Collects 20 messages per channel for conversation context
- **Idle Buffer Processing**: Background task handles conversations that stop abruptly
- **Extreme Toxicity Detection**: Immediate processing for severely negative content (< -0.8 VADER score)
- **Flexible Notifications**: Alerts to configured channel or DM to bot owner

## Installation

1. Install the required dependency:
   ```bash
   pip install nltk>=3.8.0
   ```

2. Load the cog:
   ```
   [p]load unimod
   ```

## Configuration

### Required Setup

1. **Set OpenAI API Key** (used for NanoGPT):
   ```
   [p]set api openai YOUR_API_KEY
   ```
   Or alternatively:
   ```
   [p]unimod config apikey YOUR_API_KEY
   ```

2. **Add Channels to Whitelist**:
   ```
   [p]unimod whitelist #general #chat #off-topic
   ```

3. **Enable Monitoring**:
   ```
   [p]unimod toggle
   ```

### Optional Configuration

- **Set Alert Channel** (defaults to DM owner):
   ```
   [p]unimod channel #mod-alerts
   ```

- **Adjust VADER Threshold** (-1.0 to 0.0, default -0.5):
   ```
   [p]unimod config threshold -0.6
   ```

- **Adjust Buffer Size** (10-50, default 20):
   ```
   [p]unimod config buffersize 30
   ```

## Commands

### Bot Owner Only

| Command | Description |
|---------|-------------|
| `[p]unimod toggle` | Enable/disable monitoring in this guild |
| `[p]unimod channel [#channel]` | Set alert channel (empty = DM owner) |
| `[p]unimod whitelist [#channel...]` | Add channels to monitoring whitelist |
| `[p]unimod unwhitelist [#channel...]` | Remove channels from whitelist |
| `[p]unimod clearwhitelist` | Clear all whitelisted channels |
| `[p]unimod config apikey <key>` | Set OpenAI API key (for NanoGPT) |
| `[p]unimod config threshold <value>` | Set VADER threshold (-1.0 to 0.0) |
| `[p]unimod config buffersize <int>` | Set buffer size (10-50) |
| `[p]unimod config show` | Show current configuration |
| `[p]unimod reloadrules` | Reload rules from rules.md file |

### Information Commands

| Command | Description |
|---------|-------------|
| `[p]unimod status` | Show monitoring status for this guild |
| `[p]unimod stats` | Show detection statistics |

## How It Works

### Message Flow

```
Discord Message
      ↓
  Is Bot/DM? ──Yes──→ Ignore
      ↓ No
  Is Command? ──Yes──→ Ignore
      ↓ No
  Channel Whitelisted? ──No──→ Ignore
      ↓ Yes
  Add to Buffer (max 20)
      ↓
  VADER Score < -0.5? ──No──→ Wait for buffer full
      ↓ Yes                    ↓
  Trigger AI Review ←──────────┘
      ↓
  Build Prompt with Rules
      ↓
  Send to GLM5 via NanoGPT
      ↓
  Parse JSON Response
      ↓
  Violation Detected? ──No──→ Log & Stop
      ↓ Yes
  Send Alert (Channel/DM)
```

### VADER Sentiment Analysis

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a lexicon and rule-based sentiment analysis tool specifically attuned to sentiments expressed in social media.

- **Compound Score**: Normalized weighted composite score (-1 to +1)
- **Threshold**: Messages with compound < -0.5 trigger AI review
- **Extreme Threshold**: Messages with compound < -0.8 trigger immediate review

**Important**: Each message is analyzed individually, not combined. This prevents toxicity dilution where one toxic message among many positive ones would be missed.

### AI Analysis

The GLM5 model receives:
1. **System Prompt**: Server rules from `rules.md` + operating instructions
2. **User Prompt**: Conversation log in JSON format + channel context

The AI responds with structured JSON:
```json
{
    "is_violation": true,
    "confidence": 0.85,
    "violated_rules": ["9.2", "8.1"],
    "severity": "medium",
    "explanation": "User posted venting content in general chat instead of venting channel.",
    "primary_message_id": 123456789012345678
}
```

### Anti-Censorship Design

The system prompt explicitly:
- Permits 18+ content, kink discussions, and profanity
- Instructs the AI to ONLY flag content that violates specific server rules
- Prevents false positives from AI safety filters
- Leans towards NOT flagging borderline or consensual banter

## File Structure

```
unimod/
├── __init__.py      # Cog entry point
├── unimod.py        # Main cog class
├── info.json        # Cog metadata
├── rules.md         # Server rules (edit this file)
└── README.md        # This file
```

## Customizing Rules

Edit the `rules.md` file in the cog directory to update server rules. The file uses standard Markdown format.

After editing:
1. Reload the rules: `[p]unimod reloadrules`
2. Or reload the cog: `[p]reload unimod`

## Performance Considerations

- **Non-Blocking**: AI analysis runs in background tasks, doesn't block message processing
- **Lock-Based Safety**: Per-channel asyncio.Lock prevents race conditions
- **Buffer Limits**: Deque automatically discards old messages
- **Idle Processing**: Background task (every 2 minutes) handles stale buffers

## Troubleshooting

### "OpenAI API key not configured"
Set your API key: `[p]set api openai YOUR_API_KEY`

### "No channels are being monitored"
Add channels to the whitelist: `[p]unimod whitelist #channel-name`

### "Alerts not being received"
- Check if monitoring is enabled: `[p]unimod status`
- Verify alert channel or check DM permissions
- Check bot logs for errors

### "Too many false positives"
- Adjust VADER threshold: `[p]unimod config threshold -0.7` (more negative = less sensitive)
- Review your rules.md for clarity

### "Missing violations"
- Lower the threshold: `[p]unimod config threshold -0.4` (less negative = more sensitive)
- Check if the channel is whitelisted

## Requirements

- Python 3.10+
- Red Bot 3.5.0+
- nltk >= 3.8.0
- aiohttp (pre-installed with Red)

## License

MIT License
