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

2. **Set Moderation Team Roles**:
   ```
   [p]docs config roles ROLE_ID_1 ROLE_ID_2 ROLE_ID_3
   ```

3. **Configure Database Path** (optional):
   ```
   [p]docs config database ./staff_docs_db
   ```

### Optional Configuration

- **Set Models**:
  ```
  [p]docs config models text-embedding-ada-002 openai/gpt-3.5-turbo
  ```

- **View Current Configuration**:
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
  [p]docs config database <path>
  [p]docs config roles <role_ids>
  [p]docs config models <embedding_model> <chat_model>
  [p]docs config show
  ```

## Database Indexing

The cog works with a ChromaDB database that needs to be populated with your documentation. Use the included `indexer.py` script to index your Markdown documentation:

```bash
python indexer.py
```

Make sure to set up your `.env` file with:
```
OPENROUTER_API_KEY=your_api_key_here
```

And update the paths in `indexer.py` to match your documentation structure.

## Commands

### User Commands
- `[p]docs ask <question>` - Ask a question about the documentation
- `[p]docs search <query>` - Search for specific information
- `[p]docs stats` - Show database statistics

### Owner Commands
- `[p]docs config apikey <key>` - Set OpenRouter API key
- `[p]docs config database <path>` - Set database path
- `[p]docs config roles <role_ids>` - Set moderation team roles
- `[p]docs config models <embedding> <chat>` - Set AI models
- `[p]docs config show` - Show current configuration

## Permissions

- **Moderation Team**: Can use `ask`, `search`, and `stats` commands
- **Bot Owner**: Can use all commands including configuration

## Requirements

- Python 3.8+
- Red Bot 3.5.0+
- chromadb
- requests
- python-dotenv

## Troubleshooting

1. **"OpenRouter API key not configured"**: Set your API key using `[p]docs config apikey`
2. **"You don't have permission"**: Make sure your role is added to moderation roles
3. **"No relevant information found"**: Check if the database is properly indexed
4. **Database errors**: Ensure the database path is accessible and ChromaDB is properly installed

## Support

For issues or questions, contact the bot administrator or check the bot logs for detailed error information.
