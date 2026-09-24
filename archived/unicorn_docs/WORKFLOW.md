# Unicorn Docs Workflow

Unicorn Docs indexes trusted Markdown locally at cog load and performs deterministic keyword retrieval. It does not generate, load, or deserialize pickle/vector embeddings.

## Add or update documentation

1. Add trusted `.md` files under `unicorn_docs/docs`.
2. Reload the cog so it rebuilds the in-memory keyword index.
3. Run `[p]docs stats` to confirm the file and chunk counts.
4. Test retrieval with `[p]docs search <query>`.

No local indexing script, embedding model, vector artifact, or extra Python dependency is required. Markdown files are the source of truth and may be committed through the repository's normal review process.

## Configure AI answers

Keyword search works without an external API. To let `[p]docs ask` synthesize an answer from retrieved excerpts, configure OpenRouter:

```text
[p]docs config apikey YOUR_OPENROUTER_KEY
```

The cog uses the bot's shared asynchronous HTTP session. Queries and selected documentation excerpts are sent to OpenRouter only for AI-backed answers; `[p]docs search` remains local.

## Runtime layout

```text
unicorn_docs/
├── docs/                         # Trusted Markdown corpus
├── unicorndocs_precomputed.py    # Cog and keyword index
├── README.md                     # User and operator reference
└── WORKFLOW.md                   # This maintenance workflow
```

Legacy `vectors/`, `embeddings.pkl`, and `metadata.pkl` files are ignored by the runtime and should not be regenerated or committed as part of this workflow.
