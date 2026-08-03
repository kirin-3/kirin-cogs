import asyncio
import logging
from pathlib import Path
from typing import Any

import aiohttp
import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.kirin_cogs.unicorn_docs")


class UnicornDocsPrecomputed(commands.Cog):
    """
    Unicorn documentation Q&A system.

    AI-powered documentation question and answer system for the moderation team.
    Uses deterministic keyword retrieval and OpenRouter for chat generation.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)

        # Hardcoded configuration - use absolute path based on cog location
        cog_dir = Path(__file__).parent
        self.DOCS_PATH = str(cog_dir / "docs")
        self.MODERATION_ROLES = [696020813299580940, 898586656842600549]
        self.CHAT_MODEL = "tngtech/deepseek-r1t2-chimera:free"
        self.MAX_CHUNKS = 8  # Increased for more context

        # Only API key is configurable
        default_global = {"openrouter_api_key": ""}

        self.config.register_global(**default_global)

        # In-memory keyword index built from Markdown documents.
        self._metadata = []
        self._config = {}
        self._loaded = False

    @staticmethod
    def _chunk_markdown(text: str, max_chars: int = 2000) -> list[str]:
        """Split Markdown into bounded, paragraph-aligned keyword-search chunks."""
        chunks: list[str] = []
        current: list[str] = []
        current_size = 0
        for paragraph in (part.strip() for part in text.split("\n\n")):
            if not paragraph:
                continue
            if current and current_size + len(paragraph) + 2 > max_chars:
                chunks.append("\n\n".join(current))
                current = []
                current_size = 0
            if len(paragraph) > max_chars:
                if current:
                    chunks.append("\n\n".join(current))
                    current = []
                    current_size = 0
                chunks.extend(paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars))
                continue
            current.append(paragraph)
            current_size += len(paragraph) + 2
        if current:
            chunks.append("\n\n".join(current))
        return chunks

    def _load_data_sync(self, docs_path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """Build a keyword index directly from trusted Markdown files."""
        if not docs_path.is_dir():
            raise FileNotFoundError(f"Documentation directory not found: {docs_path.absolute()}")

        files = sorted(docs_path.rglob("*.md"))
        if not files:
            raise FileNotFoundError(f"No Markdown documentation found in: {docs_path.absolute()}")

        metadata: list[dict[str, str]] = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            metadata.extend(
                {"original_text": chunk, "source_file": str(path.relative_to(docs_path))}
                for chunk in self._chunk_markdown(text)
            )

        config: dict[str, Any] = {"retrieval": "keyword", "total_files": len(files)}
        return config, metadata

    async def load_vectors(self) -> None:
        """Load the Markdown keyword index (legacy method name retained for compatibility)."""
        if self._loaded:
            return

        try:
            docs_path = Path(self.DOCS_PATH)
            log.info("Building documentation index from %s", docs_path.absolute())

            config, metadata = await asyncio.to_thread(self._load_data_sync, docs_path)

            self._config = config
            self._metadata = metadata

            log.info(f"Loaded config: {self._config}")
            log.info(f"Loaded {len(self._metadata)} metadata entries")

            self._loaded = True
            log.info("Documentation keyword index loaded successfully")

        except FileNotFoundError as e:
            log.warning(str(e))
            # Don't set loaded=True so we can retry if files appear later
        except Exception:
            log.exception("Failed to load documentation index")
            self._loaded = True  # Don't retry on other errors

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        await self.load_vectors()

    def simple_text_search(self, query: str, max_chunks: int = 8) -> list[dict[str, Any]]:
        """Enhanced text-based search with better scoring."""
        query_lower = query.lower()
        query_words = [word.strip() for word in query_lower.split() if len(word.strip()) > 2]  # Filter short words
        results = []

        for _i, metadata in enumerate(self._metadata):
            text_lower = metadata.get("original_text", "").lower()
            source_lower = metadata.get("source_file", "").lower()

            # Enhanced scoring system
            score = 0

            # Exact phrase matching (highest priority)
            if query_lower in text_lower:
                score += 10

            # Word matching with position weighting
            for word in query_words:
                if word in text_lower:
                    # Check if word appears in title/heading (higher score)
                    if text_lower.startswith(word) or f"# {word}" in text_lower:
                        score += 3
                    else:
                        score += 1

                if word in source_lower:
                    score += 0.5

            # Bonus for longer, more relevant chunks
            if score > 0:
                text_length = len(metadata.get("original_text", ""))
                if text_length > 200:  # Prefer substantial chunks
                    score += 0.5

                results.append(
                    {
                        "text": metadata.get("original_text", ""),
                        "source_file": metadata.get("source_file", "Unknown"),
                        "distance": 1.0 / (score + 1),  # Lower distance = better match
                        "score": score,
                    }
                )

        # Sort by score (descending) and return top results
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_chunks]

    async def query_database(self, question: str, max_chunks: int | None = None) -> list[dict[str, Any]]:
        """Query the database for relevant document chunks."""
        await self.load_vectors()

        if not self._loaded:
            log.warning("No vectors loaded, using text search fallback")
            return self.simple_text_search(question, max_chunks or self.MAX_CHUNKS)

        try:
            # For now, use text search as fallback
            # In a full implementation, you'd generate query embedding here
            return self.simple_text_search(question, max_chunks or self.MAX_CHUNKS)

        except Exception as e:
            log.error(f"Error querying database: {e}")
            return self.simple_text_search(question, max_chunks or self.MAX_CHUNKS)

    async def generate_answer(self, question: str, context_chunks: list[dict[str, Any]]) -> str:
        """Generate an answer using OpenRouter API with RAG context."""
        try:
            api_key = await self.config.openrouter_api_key()
            if not api_key:
                # If no API key, provide a simple response based on context
                context = "\n\n".join([chunk["text"] for chunk in context_chunks])
                return f"Based on the documentation:\n\n{context[:500]}{'...' if len(context) > 500 else ''}\n\n*Note: OpenRouter API key not configured for AI-generated answers.*"

            model = self.CHAT_MODEL

            # Build context from retrieved chunks with quality filtering
            filtered_chunks = []
            for chunk in context_chunks:
                text = chunk["text"].strip()
                # Filter out very short or low-quality chunks
                if len(text) > 50 and not text.startswith("---"):  # Skip frontmatter
                    filtered_chunks.append(text)

            context = "\n\n".join(filtered_chunks)

            # Create the prompt
            system_prompt = """You are a specialized Discord server moderation documentation assistant for the Unicornia server. Your primary purpose is to help moderation team members quickly find and understand server policies, procedures, and guidelines.

CORE RESPONSIBILITIES:
- Provide accurate, actionable information based on the provided documentation
- Help moderators understand complex procedures and policies
- Offer step-by-step guidance when procedures are available
- Clarify rules and their applications

RESPONSE GUIDELINES:
- Answer questions based ONLY on the provided documentation context
- If the context doesn't contain enough information, clearly state "This information is not available in the current documentation"
- Be concise but thorough - provide complete answers when possible
- Always cite the source file when referencing specific information
- Focus on practical, actionable information that moderators can immediately use
- If asked about procedures, provide clear step-by-step guidance
- For policy questions, explain both the rule and its practical application
- Maintain a professional, helpful tone suitable for moderation team use
- Do not make up, assume, or infer information not present in the documentation
- If multiple sources contain relevant information, synthesize them clearly
- Prioritize the most recent or authoritative information when conflicts exist

FORMAT PREFERENCES:
- Use bullet points for lists and procedures
- Use **bold** for important terms or key points
- Use `code blocks` for commands or specific text
- Structure responses logically with clear sections when appropriate"""

            user_prompt = f"""Context from documentation:
{context}

Question: {question}

Please provide a helpful answer based on the context above."""

            session: Any = getattr(self.bot, "session", None)
            if not isinstance(session, aiohttp.ClientSession) and not hasattr(session, "post"):
                raise RuntimeError("The bot HTTP session is unavailable")
            timeout = aiohttp.ClientTimeout(total=60)
            async with session.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.3,  # Lower temperature for more focused, consistent responses
                },
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                result = await response.json()
            return result["choices"][0]["message"]["content"].strip()

        except aiohttp.ClientError as e:
            log.error(f"Error generating answer: {e}")
            # Fallback to context-only response
            context = "\n\n".join([chunk["text"] for chunk in context_chunks])
            return f"Based on the documentation:\n\n{context[:500]}{'...' if len(context) > 500 else ''}\n\n*Note: Error generating AI response.*"
        except TimeoutError:
            log.error("Timeout generating answer")
            context = "\n\n".join([chunk["text"] for chunk in context_chunks])
            return f"Based on the documentation:\n\n{context[:500]}{'...' if len(context) > 500 else ''}\n\n*Note: AI response timed out.*"
        except Exception:
            log.exception("Unexpected error generating documentation answer")
            return "An unexpected error occurred while generating the answer. Please try again later."

    @commands.group(name="docs")
    @commands.guild_only()
    async def docs_group(self, ctx: commands.Context):
        """Documentation Q&A system commands."""
        pass

    @docs_group.command(name="ask")
    @commands.has_any_role(696020813299580940, 898586656842600549)
    async def ask_question(self, ctx: commands.Context, *, question: str):
        """
        Ask a question about the documentation.

        The bot will search through the documentation and provide an AI-generated answer.
        """

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
            embed = discord.Embed(title="📚 Documentation Answer", description=answer, color=0x00FF00)

            # Add source information
            sources = list(set([chunk["source_file"] for chunk in chunks]))
            if sources:
                embed.add_field(
                    name="📄 Sources",
                    value="\n".join([f"• {Path(source).name}" for source in sources[:3]]),
                    inline=False,
                )

            embed.set_footer(text=f"Question: {question[:100]}{'...' if len(question) > 100 else ''}")

            await msg.edit(content=None, embed=embed)

        except Exception:
            log.exception("Documentation question failed")
            await msg.edit(content="❌ The documentation request failed. Please try again later.")

    @docs_group.command(name="search")
    @commands.has_any_role(696020813299580940, 898586656842600549)
    async def search_docs(self, ctx: commands.Context, *, query: str):
        """
        Search for specific information in the documentation.

        Returns relevant chunks without AI-generated answers.
        """

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
                title="🔍 Search Results", description=f"Found {len(chunks)} relevant chunks:", color=0x0099FF
            )

            for i, chunk in enumerate(chunks[:5], 1):  # Limit to 5 results
                source = Path(chunk["source_file"]).name
                text_preview = chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"]

                embed.add_field(name=f"Result {i} - {source}", value=text_preview, inline=False)

            if len(chunks) > 5:
                embed.set_footer(text=f"Showing 5 of {len(chunks)} results")

            await msg.edit(content=None, embed=embed)

        except Exception:
            log.exception("Documentation search failed")
            await msg.edit(content="❌ The documentation search failed. Please try again later.")

    @docs_group.command(name="stats")
    @commands.has_any_role(696020813299580940, 898586656842600549)
    async def database_stats(self, ctx: commands.Context):
        """Show statistics about the documentation database."""

        try:
            await self.load_vectors()

            embed = discord.Embed(title="📊 Database Statistics", color=0x00FF00)

            embed.add_field(name="Total Chunks", value=str(len(self._metadata)), inline=True)
            embed.add_field(name="Documents Path", value=self.DOCS_PATH, inline=False)
            embed.add_field(name="Chat Model", value=self.CHAT_MODEL, inline=True)
            embed.add_field(name="Retrieval", value="Keyword", inline=True)

            if self._config:
                embed.add_field(name="Total Files", value=str(self._config.get("total_files", "Unknown")), inline=True)

            await ctx.send(embed=embed)

        except Exception:
            log.exception("Documentation statistics failed")
            await ctx.send("❌ Documentation statistics are temporarily unavailable.")

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
            "Documents Path": self.DOCS_PATH,
            "Chat Model": self.CHAT_MODEL,
            "Max Chunks": self.MAX_CHUNKS,
            "Moderation Roles": [f"<@&{role_id}>" for role_id in self.MODERATION_ROLES],
        }

        embed = discord.Embed(title="⚙️ Configuration", color=0x0099FF)

        for key, value in config.items():
            embed.add_field(name=key, value=str(value), inline=False)

        await ctx.send(embed=embed)


async def setup(bot: Red):
    await bot.add_cog(UnicornDocsPrecomputed(bot))
