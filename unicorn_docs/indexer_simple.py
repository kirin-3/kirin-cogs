import os
import sys
import requests
import json
import pickle
import numpy as np
from pathlib import Path
from dotenv import load_dotenv

# --- SETUP AND CONFIGURATION ---

# Load credentials from the .env file
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# The path to your MkDocs 'docs' directory
DOCS_DIRECTORY = "./docs"

# The path where you want to store the database files
DB_DIRECTORY = "./staff_docs_db"

# Configuration
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
EMBEDDING_MODEL = "text-embedding-ada-002"

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
        # Simple way to strip MkDocs frontmatter (the --- ... --- block at the top)
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) > 2:
                return parts[2].strip()
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

def get_embedding(text_chunk):
    """Sends a text chunk to OpenRouter to get its vector embedding."""
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/embeddings",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps({
                "model": EMBEDDING_MODEL,
                "input": text_chunk
            }),
            timeout=30
        )
        response.raise_for_status()
        embedding = response.json()['data'][0]['embedding']
        return embedding
    except requests.exceptions.RequestException as e:
        print(f"  -! Error getting embedding: {e}")
        return None
    except Exception as e:
        print(f"  -! Unexpected error getting embedding: {e}")
        return None

# --- MAIN EXECUTION SCRIPT ---

def main():
    """
    Orchestrates the entire process of finding, chunking, embedding,
    and storing the documentation using simple file storage.
    """
    print("--- Starting Documentation Indexing Process (Simple Version) ---")
    
    # Check if API key is available
    if not OPENROUTER_API_KEY:
        print("Error: OPENROUTER_API_KEY not found in environment variables.")
        print("Please create a .env file with your OpenRouter API key.")
        return
    
    # Check if docs directory exists
    docs_path = Path(DOCS_DIRECTORY)
    if not docs_path.exists():
        print(f"Error: Documentation directory '{DOCS_DIRECTORY}' not found.")
        print("Please check the path and ensure it exists.")
        return
    
    # 1. Find all the documentation files
    markdown_files = find_markdown_files(DOCS_DIRECTORY)
    if not markdown_files:
        print(f"Error: No Markdown files found in '{DOCS_DIRECTORY}'. Please check the path.")
        return
    
    print(f"Found {len(markdown_files)} Markdown files to process.")
    
    # Create database directory
    db_path = Path(DB_DIRECTORY)
    db_path.mkdir(exist_ok=True)
    
    # Storage lists
    all_embeddings = []
    all_metadata = []
    total_chunks = 0
    
    # Process each file
    for filepath in markdown_files:
        print(f"\nProcessing file: {filepath}")
        
        # 2. Read and parse the file content
        content = parse_markdown_file(filepath)
        if not content:
            print("  - Skipping empty file.")
            continue
            
        # 3. Split content into manageable chunks
        chunks = chunk_text(content, CHUNK_SIZE, CHUNK_OVERLAP)
        print(f"  - Split into {len(chunks)} chunks.")
        
        # 4. Process each chunk to get its embedding
        for i, chunk in enumerate(chunks):
            print(f"  - Processing chunk {i+1}/{len(chunks)}...", end=" ")
            embedding = get_embedding(chunk)
            
            # If embedding was successful, add it to our lists for storage
            if embedding:
                all_embeddings.append(embedding)
                # Store useful metadata that the bot can use later
                all_metadata.append({
                    "source_file": str(filepath), 
                    "original_text": chunk,
                    "chunk_index": i
                })
                print("✓")
            else:
                print("✗")

        total_chunks += len(chunks)
    
    # 5. Save everything to files
    try:
        embeddings_file = db_path / "embeddings.pkl"
        metadata_file = db_path / "metadata.pkl"
        
        with open(embeddings_file, 'wb') as f:
            pickle.dump(all_embeddings, f)
        with open(metadata_file, 'wb') as f:
            pickle.dump(all_metadata, f)
            
        print(f"\n--- Indexing Process Finished Successfully! ---")
        print(f"Total chunks processed: {total_chunks}")
        print(f"Total embeddings stored: {len(all_embeddings)}")
        print(f"Database saved to: {DB_DIRECTORY}")
        print("You can now use the Discord bot to query the documentation.")
        
    except Exception as e:
        print(f"Error saving database: {e}")

if __name__ == "__main__":
    main()
