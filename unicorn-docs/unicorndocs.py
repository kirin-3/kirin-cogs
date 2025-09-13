import os
import json
import asyncio
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import discord
import requests
import chromadb
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, box
from redbot.core.utils.predicates import MessagePredicate

log = logging.getLogger("red.unicorndocs")


class UnicornDocs(commands.Cog):
    """
    Unicorn Documentation Q&A System
    
    AI-powered documentation question and answer system for the moderation team.
    Uses RAG (Retrieval-Augmented Generation) with ChromaDB and OpenRouter API.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        
        # Default configuration
        default_global = {
            "openrouter_api_key": "",
            "database_path": "./staff_docs_db",
            "docs_directory": "./docs",
            "moderation_roles": [],
            "embedding_model": "text-embedding-ada-002",
            "chat_model": "openai/gpt-3.5-turbo",
            "max_chunks": 5,
            "chunk_size": 300,
            "chunk_overlap": 50
        }
        
        self.config.register_global(**default_global)
        
        # Initialize ChromaDB client
        self._client = None
        self._collection = None
        
    async def initialize_database(self):
        """Initialize ChromaDB client and collection."""
        try:
            db_path = await self.config.database_path()
            self._client = chromadb.PersistentClient(path=db_path)
            self._collection = self._client.get_or_create_collection(name="staff_documentation")
            log.info(f"ChromaDB initialized with path: {db_path}")
        except Exception as e:
            log.error(f"Failed to initialize ChromaDB: {e}")
            raise

    async def cog_load(self):
        """Called when the cog is loaded."""
        await self.initialize_database()

    def cog_unload(self):
        """Called when the cog is unloaded."""
        if self._client:
            self._client = None
            self._collection = None

    async def check_moderation_permission(self, ctx: commands.Context) -> bool:
        """Check if the user has moderation team permissions."""
        if not ctx.guild:
            return False
            
        moderation_roles = await self.config.moderation_roles()
        if not moderation_roles:
            # If no roles configured, allow server administrators
            return ctx.author.guild_permissions.administrator
        
        user_roles = [role.id for role in ctx.author.roles]
        return any(role_id in user_roles for role_id in moderation_roles)

    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """Get text embedding from OpenRouter API."""
        try:
            api_key = await self.config.openrouter_api_key()
            if not api_key:
                raise ValueError("OpenRouter API key not configured")
            
            model = await self.config.embedding_model()
            
            response = requests.post(
                url="https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                data=json.dumps({
                    "model": model,
                    "input": text
                }),
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            return result['data'][0]['embedding']
            
        except requests.exceptions.RequestException as e:
            log.error(f"Error getting embedding: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error getting embedding: {e}")
            return None

    async def query_database(self, question: str, max_chunks: int = None) -> List[Dict[str, Any]]:
        """Query the ChromaDB for relevant document chunks."""
        if not self._collection:
            await self.initialize_database()
        
        try:
            # Get embedding for the question
            question_embedding = await self.get_embedding(question)
            if not question_embedding:
                return []
            
            # Query the database
            max_chunks = max_chunks or await self.config.max_chunks()
            results = self._collection.query(
                query_embeddings=[question_embedding],
                n_results=max_chunks
            )
            
            # Format results
            chunks = []
            if results['metadatas'] and results['metadatas'][0]:
                for i, metadata in enumerate(results['metadatas'][0]):
                    chunk = {
                        'text': metadata.get('original_text', ''),
                        'source_file': metadata.get('source_file', 'Unknown'),
                        'distance': results['distances'][0][i] if results['distances'] else 0
                    }
                    chunks.append(chunk)
            
            return chunks
            
        except Exception as e:
            log.error(f"Error querying database: {e}")
            return []

    async def generate_answer(self, question: str, context_chunks: List[Dict[str, Any]]) -> str:
        """Generate an answer using OpenRouter API with RAG context."""
        try:
            api_key = await self.config.openrouter_api_key()
            if not api_key:
                raise ValueError("OpenRouter API key not configured")
            
            model = await self.config.chat_model()
            
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
            return f"Error generating answer: {e}"
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
        
        # Check if API key is configured
        api_key = await self.config.openrouter_api_key()
        if not api_key:
            await ctx.send("❌ OpenRouter API key not configured. Please contact an administrator.")
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
                    value="\n".join([f"• {source}" for source in sources[:3]]),
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
        
        # Check if API key is configured
        api_key = await self.config.openrouter_api_key()
        if not api_key:
            await ctx.send("❌ OpenRouter API key not configured. Please contact an administrator.")
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
            if not self._collection:
                await self.initialize_database()
            
            count = self._collection.count()
            
            embed = discord.Embed(
                title="📊 Database Statistics",
                color=0x00ff00
            )
            
            embed.add_field(name="Total Chunks", value=str(count), inline=True)
            embed.add_field(name="Database Path", value=await self.config.database_path(), inline=False)
            embed.add_field(name="Embedding Model", value=await self.config.embedding_model(), inline=True)
            embed.add_field(name="Chat Model", value=await self.config.chat_model(), inline=True)
            
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

    @config_group.command(name="database")
    async def set_database_path(self, ctx: commands.Context, path: str):
        """Set the ChromaDB database path."""
        await self.config.database_path.set(path)
        await self.initialize_database()
        await ctx.send(f"✅ Database path updated to: {path}")

    @config_group.command(name="roles")
    async def set_moderation_roles(self, ctx: commands.Context, *role_ids: int):
        """Set moderation team role IDs."""
        await self.config.moderation_roles.set(list(role_ids))
        await ctx.send(f"✅ Moderation roles updated: {role_ids}")

    @config_group.command(name="models")
    async def set_models(self, ctx: commands.Context, embedding_model: str, chat_model: str):
        """Set the embedding and chat models."""
        await self.config.embedding_model.set(embedding_model)
        await self.config.chat_model.set(chat_model)
        await ctx.send(f"✅ Models updated - Embedding: {embedding_model}, Chat: {chat_model}")

    @config_group.command(name="show")
    async def show_config(self, ctx: commands.Context):
        """Show current configuration."""
        config = {
            "Database Path": await self.config.database_path(),
            "Embedding Model": await self.config.embedding_model(),
            "Chat Model": await self.config.chat_model(),
            "Max Chunks": await self.config.max_chunks(),
            "Moderation Roles": await self.config.moderation_roles()
        }
        
        embed = discord.Embed(
            title="⚙️ Configuration",
            color=0x0099ff
        )
        
        for key, value in config.items():
            if key == "Moderation Roles":
                value = [f"<@&{role_id}>" for role_id in value] if value else "Not configured"
            embed.add_field(name=key, value=str(value), inline=False)
        
        await ctx.send(embed=embed)


async def setup(bot: Red):
    await bot.add_cog(UnicornDocs(bot))
