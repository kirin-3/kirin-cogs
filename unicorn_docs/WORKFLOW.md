# UnicornDocs Workflow

This document explains the two-step workflow for using UnicornDocs:

## 🔄 **Two-Step Process**

### **Step 1: Local Indexing (Your Machine)**
Run the indexer on your local machine to process documentation and generate vectors:

```bash
# Install sentence-transformers locally
pip install sentence-transformers

# Run the indexer
python indexer_local_standalone.py
```

This will:
- ✅ Read all `.md` files from `./docs/` folder
- ✅ Chunk the content into manageable pieces
- ✅ Generate embeddings using sentence-transformers
- ✅ Save vectors to `./vectors/` folder
- ✅ Create configuration files

### **Step 2: Git Commit & Deploy**
Commit the generated vectors to git:

```bash
git add vectors/
git commit -m "Update documentation vectors"
git push
```

### **Step 3: Bot Usage**
The bot loads the pre-computed vectors and uses OpenRouter for chat:

```bash
# Bot only needs these lightweight dependencies
pip install requests python-dotenv numpy

# Load the cog
[p]load unicorn_docs

# Configure (only API key needed)
[p]docs config apikey YOUR_OPENROUTER_KEY

# Use it
[p]docs ask What is our moderation policy?
```

## 📁 **File Structure**

```
unicorn_docs/
├── docs/                    # Your documentation (gitignored)
│   ├── policy.md
│   ├── rules.md
│   └── ...
├── vectors/                 # Generated vectors (committed to git)
│   ├── embeddings.pkl
│   ├── metadata.pkl
│   └── config.json
├── indexer_local_standalone.py  # Run this locally
├── unicorndocs_precomputed.py   # Bot cog
└── .gitignore              # Ignores docs/ folder
```

## ⚡ **Benefits**

- ✅ **Fast Bot Performance** - No heavy ML models on bot server
- ✅ **Lightweight Dependencies** - Bot only needs basic packages
- ✅ **Version Controlled** - Vectors are tracked in git
- ✅ **Easy Updates** - Just re-run indexer and commit
- ✅ **Cost Effective** - Only uses OpenRouter for chat, not embeddings

## 🔧 **Configuration**

### **Local Indexer Settings**
Edit `indexer_local_standalone.py`:
```python
DOCS_DIRECTORY = "./docs"           # Your docs folder
OUTPUT_DIRECTORY = "./vectors"      # Where to save vectors
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Embedding model
CHUNK_SIZE = 300                    # Words per chunk
CHUNK_OVERLAP = 50                  # Overlap between chunks
```

### **Bot Settings**
```bash
[p]docs config apikey YOUR_KEY       # OpenRouter API key (only setting needed)
```

**Hardcoded Settings:**
- Vectors Path: `./vectors`
- Chat Model: `deepseek/deepseek-chat-v3.1:free`
- Moderation Roles: `696020813299580940`, `898586656842600549`

## 🚀 **Quick Start**

1. **Add your docs** to `./docs/` folder
2. **Run indexer**: `python indexer_local_standalone.py`
3. **Commit vectors**: `git add vectors/ && git commit -m "Update vectors"`
4. **Deploy bot** with the cog loaded
5. **Configure bot** with API key: `[p]docs config apikey YOUR_KEY`
6. **Start using**: `[p]docs ask What is our policy?`

## 🔄 **Updating Documentation**

When you update documentation:
1. Update files in `./docs/` folder
2. Run `python indexer_local_standalone.py`
3. Commit the new vectors: `git add vectors/ && git commit -m "Update vectors"`
4. Deploy to bot server

The bot will automatically load the new vectors on restart!
