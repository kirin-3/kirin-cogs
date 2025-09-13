# UnicornDocs - Documentation Q&A System

A Red bot cog that provides AI-powered question and answer functionality for documentation using RAG (Retrieval-Augmented Generation) with ChromaDB and OpenRouter API.

## Features

- **AI-Powered Q&A**: Ask questions about documentation and get intelligent answers
- **Vector Search**: Uses ChromaDB for efficient similarity search across documentation
- **RAG Integration**: Combines retrieval and generation for accurate, context-aware responses
- **Moderation Team Only**: Restricted to authorized moderation team members
- **Configurable**: Flexible configuration for API keys, models, and permissions

## Installation

1. Install the required dependencies:
   ```bash
   pip install chromadb requests python-dotenv
   ```

2. Load the cog in your Red bot:
   ```
   [p]load unicorndocs
   ```

## Configuration

### Required Setup

1. **Set OpenRouter API Key**:
   ```
   [p]docs config apikey YOUR_OPENROUTER_API_KEY
   ```

### Hardcoded Settings

- **Vectors Path**: `./vectors` (pre-computed vectors)
- **Chat Model**: `mistralai/mistral-small-3.2-24b-instruct:free`
- **Moderation Roles**: `696020813299580940`, `898586656842600549`
- **Max Chunks**: 5

### View Configuration

- **Show Current Settings**:
  ```
  [p]docs config show
  ```

## Usage

### For Moderation Team Members

- **Ask Questions**:
  ```
  [p]docs ask What is the policy for self-promotion?
  ```

- **Search Documentation**:
  ```
  [p]docs search self-promotion policy
  ```

- **View Database Statistics**:
  ```
  [p]docs stats
  ```

### For Bot Owners

- **Configuration Commands**:
  ```
  [p]docs config apikey <key>
  [p]docs config show
  ```

## Database Indexing

The cog works with pre-computed vectors that need to be generated locally. Use the included `indexer_local_standalone.py` script to process your Markdown documentation:

```bash
# Install sentence-transformers locally
pip install sentence-transformers

# Run the indexer
python indexer_local_standalone.py
```

This will process all `.md` files in the `./docs/` folder and generate vectors in the `./vectors/` folder. Commit these vectors to git for the bot to use.

## Commands

### User Commands
- `[p]docs ask <question>` - Ask a question about the documentation
- `[p]docs search <query>` - Search for specific information
- `[p]docs stats` - Show database statistics

### Owner Commands
- `[p]docs config apikey <key>` - Set OpenRouter API key
- `[p]docs config show` - Show current configuration

## Permissions

- **Moderation Team** (Roles: `696020813299580940`, `898586656842600549`): Can use `ask`, `search`, and `stats` commands
- **Bot Owner**: Can use all commands including configuration

## Requirements

- Python 3.8+
- Red Bot 3.5.0+
- requests
- python-dotenv
- numpy

## Troubleshooting

1. **"OpenRouter API key not configured"**: Set your API key using `[p]docs config apikey`
2. **"You don't have permission"**: Make sure you have one of the moderation team roles
3. **"No relevant information found"**: Check if the vectors are properly generated and committed to git
4. **Vector loading errors**: Ensure the `./vectors/` folder exists and contains the required files

## Support

For issues or questions, contact the bot administrator or check the bot logs for detailed error information.
