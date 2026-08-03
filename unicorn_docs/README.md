# Unicorn Docs

Unicorn Docs provides moderation-team search and question answering over Markdown files in `unicorn_docs/docs`.

## Retrieval

At cog load, Markdown files are read in a worker thread and split into bounded paragraph-aligned chunks. Searches use deterministic keyword scoring. Legacy pickle/vector files are not loaded or deserialized and are not runtime dependencies.

## AI answers

`[p]docs ask <question>` retrieves local context and, when configured, sends the question and selected excerpts to OpenRouter. Requests use the bot's shared async HTTP session with a 60-second timeout. Errors shown to Discord are sanitized.

Set the API key with `[p]docs config apikey <key>`. Without a key, the cog returns a context-only excerpt. `[p]docs search <query>` never calls the AI provider.

## Operations

- Place trusted `.md` documents under `unicorn_docs/docs` and reload the cog to rebuild the in-memory index.
- `[p]docs stats` reports the document path, file/chunk counts, model, and keyword retrieval mode.
- The cog stores configuration only. It does not retain per-user query records, but OpenRouter receives queries and excerpts when AI answers are enabled.
- Red supplies the runtime HTTP dependency; `requirements.txt` intentionally lists no extra package.
