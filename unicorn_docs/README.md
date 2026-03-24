# UnicornDocs - Documentation Q&A System

A Red Discord Bot cog that provides AI-powered question and answer functionality for documentation using RAG (Retrieval-Augmented Generation) with pre-computed vector embeddings and OpenRouter API.

## Features

- **AI-Powered Q&A**: Ask questions about documentation and get intelligent, context-aware answers
- **Vector Search**: Uses pre-computed embeddings with efficient similarity search across documentation
- **RAG Integration**: Combines retrieval and generation for accurate responses based on your documentation
- **Text Search Fallback**: Automatically falls back to enhanced text-based search if vectors aren't loaded
- **Moderation Team Only**: Restricted to authorized moderation team members (configurable roles)
- **Embed Responses**: Returns answers in formatted Discord embeds with source citations
- **Configurable**: Flexible configuration for API keys, models, and permissions

## Installation

1. **Install the required dependencies**:
    ```bash
    pip install requests python-dotenv numpy
    ```
    
    For indexing documentation locally (optional - only needed if you want to regenerate vectors):
    ```bash
    pip install sentence-transformers
    ```

2. **Load the cog in your Red bot**:
    ```
    [p]load unicorndocs
    ```
    
    The cog will automatically attempt to load pre-computed vectors from the `./vectors/` folder on startup.

## Configuration

### Required Setup

1. **Set OpenRouter API Key** (Bot Owner only):
    ```
    [p]docs config apikey YOUR_OPENROUTER_API_KEY
    ```
    
    Get your API key from [OpenRouter](https://openrouter.ai/keys). Without this, the bot will still work but will provide context-only responses without AI generation.

### Hardcoded Settings

These settings are configured in the cog code:

- **Vectors Path**: `./vectors/` (relative to cog folder, contains pre-computed embeddings)
- **Chat Model**: `tngtech/deepseek-r1t2-chimera:free` (OpenRouter model for generating answers)
- **Moderation Roles**: `696020813299580940`, `898586656842600549` (Discord role IDs that can use the commands)
- **Max Chunks**: 8 (number of document chunks retrieved per query)
- **Temperature**: 0.3 (lower temperature for more focused, consistent responses)

### View Configuration

- **Show Current Settings** (Bot Owner only):
  ```
  [p]docs config show
  ```
  
  This displays the current vectors path, chat model, max chunks, and moderation role mentions.

## Usage

### For Moderation Team Members

- **Ask Questions** (AI-powered answer with sources):
  ```
  [p]docs ask What is the policy for self-promotion?
  ```
  The bot will search the documentation, retrieve relevant chunks, and generate an AI-powered answer with source citations.

- **Search Documentation** (raw search results):
  ```
  [p]docs search self-promotion policy
  ```
  Returns up to 5 relevant document chunks without AI generation. Useful for quick lookups.

- **View Database Statistics**:
  ```
  [p]docs stats
  ```
  Shows total chunks loaded, vectors path, chat model, and embedding information.

### For Bot Owners

- **Set OpenRouter API Key**:
  ```
  [p]docs config apikey <your_api_key>
  ```

- **View Configuration**:
  ```
  [p]docs config show
  ```
  
### How It Works

1. **Query Processing**: When you ask a question, the cog searches through pre-computed vector embeddings
2. **Chunk Retrieval**: Retrieves the top 8 most relevant document chunks using enhanced text scoring
3. **AI Generation**: Sends the context to OpenRouter API to generate a coherent answer
4. **Response**: Returns a formatted embed with the answer and source file citations

If vectors aren't loaded or the API key isn't set, the cog falls back to text-based search and provides context-only responses.

## Database Indexing

The cog uses **pre-computed vector embeddings** that must be generated locally before the bot can search your documentation. This is a one-time process (or run it again whenever your documentation changes).

### Indexing Workflow

1. **Prepare Your Documentation**:
   - Place all Markdown (`.md`) files in the `./docs/` folder relative to the cog
   - The indexer will recursively find all `.md` files in subdirectories

2. **Install Indexing Dependencies**:
   ```bash
   pip install sentence-transformers
   ```

3. **Run the Indexer**:
   ```bash
   python indexer_local_standalone.py
   ```
   
   This will:
   - Read all Markdown files from `./docs/`
   - Strip MkDocs frontmatter (the `---` YAML blocks)
   - Split content into overlapping chunks (500 words with 100 word overlap)
   - Generate embeddings using the configured model
   - Save vectors to `./vectors/` folder

4. **Commit Vectors to Git**:
   ```bash
   git add vectors/
   git commit -m "Update documentation vectors"
   git push
   ```

### Embedding Model Options

The indexer uses `nomic-ai/nomic-embed-text-v1` by default (highest quality). You can change this in `indexer_local_standalone.py`:

- **`all-MiniLM-L6-v2`** - FASTEST (~80MB, good for testing)
- **`all-mpnet-base-v2`** - RECOMMENDED (~420MB, best balance)
- **`nomic-ai/nomic-embed-text-v1`** - HIGHEST QUALITY (~500MB, best accuracy)
- **`all-MiniLM-L12-v2`** - MIDDLE GROUND (~120MB, good compromise)

### Generated Files

The indexer creates these files in `./vectors/`:
- `embeddings.pkl` - Vector embeddings for all chunks
- `metadata.pkl` - Metadata (source file, original text, chunk index)
- `config.json` - Configuration info (model, chunk size, totals)

### When to Re-index

Re-run the indexer when:
- You add new documentation files
- You modify existing documentation content
- You want to change the embedding model
- You adjust chunk size/overlap settings

## Commands

### Moderation Team Commands

These commands require one of the configured moderation roles:

- **`[p]docs ask <question>`**
  - Ask a natural language question about the documentation
  - Returns an AI-generated answer with source citations
  - Shows "Searching documentation..." and "Generating answer..." status updates
  - **Example**: `[p]docs ask How do I handle spam reports?`

- **`[p]docs search <query>`**
  - Search for specific keywords or phrases in the documentation
  - Returns up to 5 relevant document chunks with source files
  - No AI generation - shows raw search results
  - **Example**: `[p]docs search spam moderation`

- **`[p]docs stats`**
  - Display database statistics
  - Shows: total chunks, vectors path, chat model, embedding type
  - **Example**: `[p]docs stats`

### Bot Owner Commands

- **`[p]docs config apikey <key>`**
  - Set the OpenRouter API key for AI answer generation
  - Required for AI-powered answers (cog works without it but provides context-only responses)
  - **Example**: `[p]docs config apikey sk-or-v1-...`

- **`[p]docs config show`**
  - Display current configuration
  - Shows: vectors path, chat model, max chunks, moderation roles (as mentions)
  - **Example**: `[p]docs config show`

### Command Group

- **`[p]docs`** - Base command group (shows help when used without subcommand)

## Permissions

### Role Requirements

- **Moderation Team** (Default Role IDs: `696020813299580940`, `898586656842600549`):
  - Can use: `[p]docs ask`, `[p]docs search`, `[p]docs stats`
  - Must have **at least one** of these roles to access moderation commands
  - To change these role IDs, edit the `MODERATION_ROLES` list in `unicorndocs_precomputed.py`

- **Bot Owner**:
  - Can use all commands including `[p]docs config apikey` and `[p]docs config show`
  - Has unrestricted access to configuration

### Discord Permissions

The cog requires no special Discord permissions beyond:
- **Send Messages** - To respond to commands
- **Embed Links** - To display formatted responses (recommended)
- **Read Message History** - May be required in some server configurations

## Requirements

### Runtime Requirements (for the bot)
- **Python**: 3.11+
- **Red-DiscordBot**: 3.5.0+
- **Dependencies**:
  - `requests` (>=2.25.0) - HTTP requests to OpenRouter API
  - `python-dotenv` (>=0.19.0) - Environment variable support
  - `numpy` (>=1.21.0) - Vector similarity calculations

### Indexing Requirements (for generating vectors locally)
- **sentence-transformers** - For generating text embeddings
- **Python 3.11+** - Same as bot runtime

### Optional
- **OpenRouter API Key** - For AI-powered answer generation (cog works without it but provides context-only responses)

## Troubleshooting

### Common Issues

**"OpenRouter API key not configured"**
- Set your API key using `[p]docs config apikey <your_key>`
- Get a key from [OpenRouter](https://openrouter.ai/keys)
- The cog still works without a key but provides context-only responses

**"You don't have permission to use this command"**
- Ensure you have one of the moderation team roles configured in the cog
- Default role IDs: `696020813299580940`, `898586656842600549`
- Contact a server admin to add you to the moderation team
- To change roles, edit `MODERATION_ROLES` in `unicorndocs_precomputed.py`

**"No relevant information found"**
- Verify vectors are properly generated and committed to git
- Check that `./vectors/` contains `embeddings.pkl`, `metadata.pkl`, and `config.json`
- Ensure your documentation files are in `./docs/` and were indexed
- Try re-running `python indexer_local_standalone.py` to regenerate vectors

**Vector loading errors on cog startup**
- Ensure the `./vectors/` folder exists relative to the cog folder
- Check file permissions - the bot must be able to read `.pkl` and `.json` files
- Verify the files aren't corrupted (try regenerating them)
- Check bot logs for detailed error messages

**Slow response times**
- Normal: AI generation takes 5-30 seconds depending on OpenRouter API load
- If consistently slow, check your internet connection and OpenRouter status
- The cog uses a free model which may have rate limits

**Answers seem generic or off-topic**
- This may indicate the API key isn't set (cog falls back to context-only mode)
- Check with `[p]docs config show` to verify configuration
- Ensure your documentation contains relevant information for the query
- Try more specific queries with keywords from your documentation

**Embeds not displaying**
- Ensure the bot has "Embed Links" permission in the channel
- Some Discord clients may not render embeds properly (try desktop app)

### Checking Cog Status

Use `[p]docs stats` to verify:
- Total chunks loaded (should be > 0)
- Vectors path is correct
- Chat model is configured

Check bot logs for messages like:
- `Loaded X embeddings` - Vectors loaded successfully
- `No vectors loaded, using text search fallback` - Using text search instead
- `Failed to load vectors` - Check vectors folder and files

## Support

For issues or questions, contact the bot administrator or check the bot logs for detailed error information.

## Data Storage

### What Gets Stored

- **Vector Embeddings**: Pre-computed embeddings of your documentation content (stored in `./vectors/embeddings.pkl`)
- **Metadata**: Document chunk metadata including source file and original text (stored in `./vectors/metadata.pkl`)
- **Configuration**: OpenRouter API key (stored in Red's Config system, encrypted)

### What Does NOT Get Stored

- No user data is stored persistently
- No conversation history is retained between queries
- No personal information is logged or tracked

### End User Data Statement

> This cog stores vector embeddings of documentation content for AI-powered question answering. No personal user data is stored or transmitted to external services beyond the query text sent to OpenRouter API for answer generation.

## AI Response Behavior

### System Prompt

The AI is configured with a specialized system prompt that:
- Focuses on Discord moderation documentation assistance
- Provides accurate, actionable information based **only** on the provided context
- Cites source files when referencing information
- Uses bullet points, bold text, and code blocks for clarity
- States clearly when information is not available in the documentation

### Response Quality

- **Temperature**: 0.3 (lower = more focused, less creative)
- **Max Tokens**: 1000 (limits response length)
- **Context Chunks**: Up to 8 document chunks retrieved per query
- **Fallback**: If AI generation fails, returns raw context from documentation

## Best Practices

### For Documentation Authors

1. **Use Clear Headings**: Structure docs with `#`, `##`, `###` headings for better chunking
2. **Avoid Very Long Sections**: Break up long walls of text into smaller sections
3. **Use Consistent Terminology**: Helps the search match queries to content
4. **Include Examples**: Step-by-step procedures work well with the AI

### For Users

1. **Be Specific**: "How do I ban a user?" works better than "ban"
2. **Use Natural Language**: Ask full questions, not just keywords
3. **Check Sources**: Review the cited source files for complete context
4. **Use Search for Quick Lookups**: `[p]docs search` is faster for simple queries

### For Administrators

1. **Re-index After Changes**: Run the indexer whenever documentation is updated
2. **Monitor API Usage**: Check OpenRouter dashboard for usage and costs
3. **Test Queries**: Periodically test common questions to ensure quality
4. **Keep Vectors in Git**: Commit `./vectors/` folder to version control

## Technical Details

### Search Algorithm

The cog uses an enhanced text-based search with scoring:
- **Exact phrase matches**: +10 points
- **Word matches in text**: +1 point
- **Word matches in headings**: +3 points
- **Word matches in source filename**: +0.5 points
- **Longer chunks (>200 chars)**: +0.5 points

Results are sorted by score and top 8 are used for AI context.

### File Structure

```
unicorn_docs/
├── unicorndocs_precomputed.py  # Main cog file
├── indexer_local_standalone.py # Vector generation script
├── docs/                       # Your Markdown documentation (for indexing)
├── vectors/                    # Pre-computed vectors (commit to git)
│   ├── embeddings.pkl
│   ├── metadata.pkl
│   └── config.json
├── requirements.txt
└── README.md
```
