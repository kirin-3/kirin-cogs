#!/usr/bin/env python3
"""
Standalone Documentation Indexer for UnicornDocs

This script runs on your local machine to:
1. Read documentation from ./docs/ folder
2. Chunk the content
3. Generate embeddings using sentence-transformers
4. Save the vectors to be committed to git

The bot will then load these pre-computed vectors for fast querying.
"""

import os
import sys
import pickle
import json
from pathlib import Path
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION ---

# The path to your docs directory (relative to this script)
DOCS_DIRECTORY = "./docs"

# The path where to save the processed vectors
OUTPUT_DIRECTORY = "./vectors"

# Embedding model options (uncomment the one you want to use)
# 
# SPEED vs ACCURACY TRADE-OFFS:
# 
# 1. "all-MiniLM-L6-v2" - FASTEST
#    - 22M parameters, ~80MB download
#    - Fastest processing, good for quick testing
#    - Lower accuracy but still decent
#
# 2. "all-mpnet-base-v2" - RECOMMENDED
#    - 110M parameters, ~420MB download  
#    - Good balance of speed and accuracy
#    - Trained on 1B+ sentence pairs
#    - Best for most use cases
#
# 3. "nomic-ai/nomic-embed-text-v1" - HIGHEST QUALITY
#    - 137M parameters, ~500MB download
#    - Best accuracy, multilingual support
#    - Slower but most accurate results
#    - Good for complex documentation
#
# 4. "sentence-transformers/all-MiniLM-L12-v2" - MIDDLE GROUND
#    - 33M parameters, ~120MB download
#    - Better than L6, faster than mpnet
#    - Good compromise option

EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1"  # Recommended: Good balance of speed and accuracy

# Chunking configuration - Optimized for better context
CHUNK_SIZE = 500  # Increased for more context per chunk
CHUNK_OVERLAP = 100  # Increased overlap for better continuity

# --- CORE FUNCTIONS ---

def find_markdown_files(directory):
    """Recursively finds all Markdown files (.md) in a given directory."""
    markdown_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".md"):
                markdown_files.append(os.path.join(root, file))
    return markdown_files

def parse_markdown_file(filepath):
    """Reads the content of a Markdown file and strips any frontmatter."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Strip MkDocs frontmatter (the --- ... --- block at the top)
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) > 2:
                content = parts[2].strip()
        
        return content.strip()
    except Exception as e:
        print(f"Error reading file {filepath}: {e}")
        return ""

def chunk_text(text, chunk_size=300, chunk_overlap=50):
    """Splits text into smaller, overlapping chunks."""
    words = text.split()
    if not words:
        return []
    
    chunks = []
    current_pos = 0
    while current_pos < len(words):
        start_pos = current_pos
        end_pos = min(current_pos + chunk_size, len(words))
        chunk_words = words[start_pos:end_pos]
        chunk_text = " ".join(chunk_words)
        
        if chunk_text.strip():  # Only add non-empty chunks
            chunks.append(chunk_text)
        
        # Move to next chunk position
        current_pos += chunk_size - chunk_overlap
        
        # Prevent infinite loop
        if current_pos >= len(words):
            break
        
    return chunks

def main():
    """Main indexing process."""
    print("🚀 UnicornDocs Local Indexer")
    print("=" * 50)
    
    # Check if docs directory exists
    docs_path = Path(DOCS_DIRECTORY)
    if not docs_path.exists():
        print(f"❌ Error: Documentation directory '{DOCS_DIRECTORY}' not found.")
        print("Please create a 'docs' folder and add your markdown files.")
        return 1
    
    # Find all markdown files
    markdown_files = find_markdown_files(DOCS_DIRECTORY)
    if not markdown_files:
        print(f"❌ Error: No Markdown files found in '{DOCS_DIRECTORY}'.")
        print("Please add some .md files to the docs folder.")
        return 1
    
    print(f"📁 Found {len(markdown_files)} Markdown files to process")
    
    # Load the embedding model
    print(f"🤖 Loading embedding model: {EMBEDDING_MODEL}")
    print("   (This may take a moment on first run...)")
    try:
        model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
        print("   ✅ Model loaded successfully!")
    except Exception as e:
        print(f"   ❌ Error loading model: {e}")
        print("   Make sure sentence-transformers is installed:")
        print("   pip install sentence-transformers")
        return 1
    
    # Create output directory
    output_path = Path(OUTPUT_DIRECTORY)
    output_path.mkdir(exist_ok=True)
    
    # Process files
    all_embeddings = []
    all_metadata = []
    total_chunks = 0
    
    print(f"\n📝 Processing files...")
    for i, filepath in enumerate(markdown_files, 1):
        print(f"\n[{i}/{len(markdown_files)}] Processing: {filepath}")
        
        # Read and parse file
        content = parse_markdown_file(filepath)
        if not content:
            print("   ⏭️  Skipping empty file")
            continue
        
        # Chunk the content
        chunks = chunk_text(content, CHUNK_SIZE, CHUNK_OVERLAP)
        print(f"   📄 Split into {len(chunks)} chunks")
        
        # Process each chunk
        file_embeddings = []
        file_metadata = []
        
        for j, chunk in enumerate(chunks):
            print(f"   🔄 Processing chunk {j+1}/{len(chunks)}...", end=" ")
            
            try:
                # Generate embedding
                embedding = model.encode(chunk, convert_to_tensor=False)
                
                # Store data
                file_embeddings.append(embedding.tolist())
                file_metadata.append({
                    "source_file": str(filepath),
                    "original_text": chunk,
                    "chunk_index": j,
                    "file_name": Path(filepath).name
                })
                
                print("✅")
                
            except Exception as e:
                print(f"❌ Error: {e}")
                continue
        
        # Add to global lists
        all_embeddings.extend(file_embeddings)
        all_metadata.extend(file_metadata)
        total_chunks += len(chunks)
        
        print(f"   ✅ Processed {len(file_embeddings)} chunks from this file")
    
    # Save the results
    print(f"\n💾 Saving results...")
    try:
        # Save embeddings
        embeddings_file = output_path / "embeddings.pkl"
        with open(embeddings_file, 'wb') as f:
            pickle.dump(all_embeddings, f)
        
        # Save metadata
        metadata_file = output_path / "metadata.pkl"
        with open(metadata_file, 'wb') as f:
            pickle.dump(all_metadata, f)
        
        # Save configuration info
        config_file = output_path / "config.json"
        config = {
            "embedding_model": EMBEDDING_MODEL,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "total_chunks": total_chunks,
            "total_files": len(markdown_files),
            "version": "1.0.0"
        }
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"   ✅ Saved to {OUTPUT_DIRECTORY}/")
        print(f"   📊 Total chunks: {total_chunks}")
        print(f"   📁 Total files: {len(markdown_files)}")
        
    except Exception as e:
        print(f"   ❌ Error saving files: {e}")
        return 1
    
    print(f"\n🎉 Indexing completed successfully!")
    print(f"📤 You can now commit the '{OUTPUT_DIRECTORY}/' folder to git")
    print(f"🤖 The bot will load these pre-computed vectors for fast querying")
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
