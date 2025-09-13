import os
import json
import asyncio
import logging
import pickle
from typing import List, Dict, Any, Optional
from pathlib import Path
import numpy as np

import discord
import requests
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, box
from redbot.core.utils.predicates import MessagePredicate

log = logging.getLogger("red.unicorndocs")


class UnicornDocsPrecomputed(commands.Cog):
    """
    Unicorn Documentation Q&A System (Pre-computed Vectors)
    
    AI-powered documentation question and answer system for the moderation team.
    Uses pre-computed embeddings and OpenRouter for chat generation.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        
        # Hardcoded configuration
        self.VECTORS_PATH = "./vectors"
        self.MODERATION_ROLES = [696020813299580940, 898586656842600549]
        self.CHAT_MODEL = "deepseek/deepseek-chat-v3.1:free"
        self.MAX_CHUNKS = 5
        
        # Only API key is configurable
        default_global = {
            "openrouter_api_key": ""
        }
        
        self.config.register_global(**default_global)
        
        # Pre-computed data
        self._embeddings = []
        self._metadata = []
        self._config = {}
        self._loaded = False
        
    async def load_vectors(self):
        """Load pre-computed vectors from the vectors directory."""
        if self._loaded:
            return
            
        try:
            vectors_path = Path(self.VECTORS_PATH)
            
            # Load configuration
            config_file = vectors_path / "config.json"
            if config_file.exists():
                with open(config_file, 'r') as f:
                    self._config = json.load(f)
                log.info(f"Loaded config: {self._config}")
            
            # Load embeddings
            embeddings_file = vectors_path / "embeddings.pkl"
            if embeddings_file.exists():
                with open(embeddings_file, 'rb') as f:
                    self._embeddings = pickle.load(f)
                log.info(f"Loaded {len(self._embeddings)} embeddings")
            else:
                log.warning("No embeddings file found")
                return
            
            # Load metadata
            metadata_file = vectors_path / "metadata.pkl"
            if metadata_file.exists():
                with open(metadata_file, 'rb') as f:
                    self._metadata = pickle.load(f)
                log.info(f"Loaded {len(self._metadata)} metadata entries")
            else:
                log.warning("No metadata file found")
                return
                
            self._loaded = True
            log.info("Pre-computed vectors loaded successfully")
            
        except Exception as e:
            log.error(f"Failed to load vectors: {e}")
            self._loaded = True  # Don't retry

    async def cog_load(self):
        """Called when the cog is loaded."""
        await self.load_vectors()

    async def check_moderation_permission(self, ctx: commands.Context) -> bool:
        """Check if the user has moderation team permissions."""
        if not ctx.guild:
            return False
        
        user_roles = [role.id for role in ctx.author.roles]
        return any(role_id in user_roles for role_id in self.MODERATION_ROLES)

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """Get text embedding using the same model that was used for indexing."""
        try:
            # For now, we'll use a simple approach since we don't have the model loaded
            # In a production setup, you might want to load the same model
            # or use a different approach for query embedding
            
            # This is a placeholder - in practice, you'd need to load the same
            # sentence-transformers model that was used for indexing
            log.warning("Query embedding not implemented - using fallback search")
            return None
            
        except Exception as e:
            log.error(f"Error getting embedding: {e}")
            return None

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        try:
            a_np = np.array(a)
            b_np = np.array(b)
            
            dot_product = np.dot(a_np, b_np)
            norm_a = np.linalg.norm(a_np)
            norm_b = np.linalg.norm(b_np)
            
            if norm_a == 0 or norm_b == 0:
                return 0
            
            return dot_product / (norm_a * norm_b)
        except Exception:
            return 0

    def simple_text_search(self, query: str, max_chunks: int = 5) -> List[Dict[str, Any]]:
        """Simple text-based search as fallback when embeddings aren't available."""
        query_lower = query.lower()
        results = []
        
        for i, metadata in enumerate(self._metadata):
            text_lower = metadata.get('original_text', '').lower()
            source_lower = metadata.get('source_file', '').lower()
            
            # Simple scoring based on word matches
            score = 0
            query_words = query_lower.split()
            
            for word in query_words:
                if word in text_lower:
                    score += 1
                if word in source_lower:
                    score += 0.5
            
            if score > 0:
                results.append({
                    'text': metadata.get('original_text', ''),
                    'source_file': metadata.get('source_file', 'Unknown'),
                    'distance': 1.0 / (score + 1),  # Lower distance = better match
                    'score': score
                })
        
        # Sort by score (descending) and return top results
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:max_chunks]

    async def query_database(self, question: str, max_chunks: int = None) -> List[Dict[str, Any]]:
        """Query the database for relevant document chunks."""
        await self.load_vectors()
        
        if not self._loaded or not self._embeddings:
            log.warning("No vectors loaded, using text search fallback")
            return self.simple_text_search(question, max_chunks or self.MAX_CHUNKS)
        
        try:
            # For now, use text search as fallback
            # In a full implementation, you'd generate query embedding here
            return self.simple_text_search(question, max_chunks or self.MAX_CHUNKS)
            
        except Exception as e:
            log.error(f"Error querying database: {e}")
            return self.simple_text_search(question, max_chunks or self.MAX_CHUNKS)

    async def generate_answer(self, question: str, context_chunks: List[Dict[str, Any]]) -> str:
        """Generate an answer using OpenRouter API with RAG context."""
        try:
            api_key = await self.config.openrouter_api_key()
            if not api_key:
                # If no API key, provide a simple response based on context
                context = "\n\n".join([chunk['text'] for chunk in context_chunks])
                return f"Based on the documentation:\n\n{context[:500]}{'...' if len(context) > 500 else ''}\n\n*Note: OpenRouter API key not configured for AI-generated answers.*"
            
            model = self.CHAT_MODEL
            
            # Build context from retrieved chunks
            context = "\n\n".join([chunk['text'] for chunk in context_chunks])
            
            # Create the prompt
            system_prompt = """You are a helpful assistant for a Discord server moderation team. 
            Answer questions based ONLY on the provided documentation context. 
            If the context doesn't contain enough information to answer the question, say so clearly.
            Be concise but thorough in your responses.
            Always cite the source file when possible."""
            
            user_prompt = f"""Context from documentation:
{context}

Question: {question}

Please provide a helpful answer based on the context above."""
            
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                data=json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.7
                }),
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
            
        except requests.exceptions.RequestException as e:
            log.error(f"Error generating answer: {e}")
            # Fallback to context-only response
            context = "\n\n".join([chunk['text'] for chunk in context_chunks])
            return f"Based on the documentation:\n\n{context[:500]}{'...' if len(context) > 500 else ''}\n\n*Note: Error generating AI response.*"
        except Exception as e:
            log.error(f"Unexpected error generating answer: {e}")
            return f"Unexpected error: {e}"

    @commands.group(name="docs")
    @commands.guild_only()
    async def docs_group(self, ctx: commands.Context):
        """Documentation Q&A system commands."""
        pass

    @docs_group.command(name="ask")
    async def ask_question(self, ctx: commands.Context, *, question: str):
        """
        Ask a question about the documentation.
        
        The bot will search through the documentation and provide an AI-generated answer.
        """
        if not await self.check_moderation_permission(ctx):
            await ctx.send("❌ You don't have permission to use this command.")
            return
        
        if not question.strip():
            await ctx.send("❌ Please provide a question to ask.")
            return
        
        # Send initial response
        msg = await ctx.send("🔍 Searching documentation...")
        
        try:
            # Query the database
            chunks = await self.query_database(question)
            
            if not chunks:
                await msg.edit(content="❌ No relevant information found in the documentation.")
                return
            
            # Generate answer
            await msg.edit(content="🤖 Generating answer...")
            answer = await self.generate_answer(question, chunks)
            
            # Create embed with answer
            embed = discord.Embed(
                title="📚 Documentation Answer",
                description=answer,
                color=0x00ff00
            )
            
            # Add source information
            sources = list(set([chunk['source_file'] for chunk in chunks]))
            if sources:
                embed.add_field(
                    name="📄 Sources",
                    value="\n".join([f"• {Path(source).name}" for source in sources[:3]]),
                    inline=False
                )
            
            embed.set_footer(text=f"Question: {question[:100]}{'...' if len(question) > 100 else ''}")
            
            await msg.edit(content=None, embed=embed)
            
        except Exception as e:
            log.error(f"Error in ask_question: {e}")
            await msg.edit(content=f"❌ An error occurred: {e}")

    @docs_group.command(name="search")
    async def search_docs(self, ctx: commands.Context, *, query: str):
        """
        Search for specific information in the documentation.
        
        Returns relevant chunks without AI-generated answers.
        """
        if not await self.check_moderation_permission(ctx):
            await ctx.send("❌ You don't have permission to use this command.")
            return
        
        if not query.strip():
            await ctx.send("❌ Please provide a search query.")
            return
        
        msg = await ctx.send("🔍 Searching documentation...")
        
        try:
            chunks = await self.query_database(query, max_chunks=10)
            
            if not chunks:
                await msg.edit(content="❌ No relevant information found.")
                return
            
            # Create embed with search results
            embed = discord.Embed(
                title="🔍 Search Results",
                description=f"Found {len(chunks)} relevant chunks:",
                color=0x0099ff
            )
            
            for i, chunk in enumerate(chunks[:5], 1):  # Limit to 5 results
                source = Path(chunk['source_file']).name
                text_preview = chunk['text'][:200] + "..." if len(chunk['text']) > 200 else chunk['text']
                
                embed.add_field(
                    name=f"Result {i} - {source}",
                    value=text_preview,
                    inline=False
                )
            
            if len(chunks) > 5:
                embed.set_footer(text=f"Showing 5 of {len(chunks)} results")
            
            await msg.edit(content=None, embed=embed)
            
        except Exception as e:
            log.error(f"Error in search_docs: {e}")
            await msg.edit(content=f"❌ An error occurred: {e}")

    @docs_group.command(name="stats")
    async def database_stats(self, ctx: commands.Context):
        """Show statistics about the documentation database."""
        if not await self.check_moderation_permission(ctx):
            await ctx.send("❌ You don't have permission to use this command.")
            return
        
        try:
            await self.load_vectors()
            
            embed = discord.Embed(
                title="📊 Database Statistics",
                color=0x00ff00
            )
            
            embed.add_field(name="Total Chunks", value=str(len(self._embeddings)), inline=True)
            embed.add_field(name="Vectors Path", value=self.VECTORS_PATH, inline=False)
            embed.add_field(name="Chat Model", value=self.CHAT_MODEL, inline=True)
            embed.add_field(name="Embedding Type", value="Pre-computed", inline=True)
            
            if self._config:
                embed.add_field(name="Indexed Model", value=self._config.get('embedding_model', 'Unknown'), inline=True)
                embed.add_field(name="Total Files", value=str(self._config.get('total_files', 'Unknown')), inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Error in database_stats: {e}")
            await ctx.send(f"❌ An error occurred: {e}")

    @docs_group.group(name="config")
    @commands.is_owner()
    async def config_group(self, ctx: commands.Context):
        """Configuration commands for the documentation system."""
        pass

    @config_group.command(name="apikey")
    async def set_api_key(self, ctx: commands.Context, api_key: str):
        """Set the OpenRouter API key."""
        await self.config.openrouter_api_key.set(api_key)
        await ctx.send("✅ OpenRouter API key updated.")

    @config_group.command(name="show")
    async def show_config(self, ctx: commands.Context):
        """Show current configuration."""
        config = {
            "Vectors Path": self.VECTORS_PATH,
            "Chat Model": self.CHAT_MODEL,
            "Max Chunks": self.MAX_CHUNKS,
            "Moderation Roles": [f"<@&{role_id}>" for role_id in self.MODERATION_ROLES]
        }
        
        embed = discord.Embed(
            title="⚙️ Configuration",
            color=0x0099ff
        )
        
        for key, value in config.items():
            embed.add_field(name=key, value=str(value), inline=False)
        
        await ctx.send(embed=embed)


async def setup(bot: Red):
    await bot.add_cog(UnicornDocsPrecomputed(bot))
