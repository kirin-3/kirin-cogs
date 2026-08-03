"""Unit and integration tests for the Suggest cog."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio
from redbot.core.bot import Red
from redbot.core.commands import Context

from suggest.suggest import DOWN_EMOJI_ID, SUGGEST_CHANNEL_ID, UP_EMOJI_ID, Suggest
from suggest.views import StickyView, SuggestionModal


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.get_channel = MagicMock()
    bot.get_emoji = MagicMock()
    bot.get_embed_color = AsyncMock(return_value=discord.Color.blue())
    bot.fetch_user = AsyncMock()
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.id = 999999
    bot.owner_ids = {12345}
    return bot


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock) -> Suggest:
    cog_instance = Suggest(bot_mock)

    # Mock config
    config_mock = MagicMock()
    config_mock.schema_version = AsyncMock(return_value=0)
    config_mock.schema_version.set = AsyncMock()
    config_mock.next_id = AsyncMock(return_value=132)
    config_mock.next_id.set = AsyncMock()
    config_mock.sticky_message_id = AsyncMock(return_value=None)
    config_mock.sticky_message_id.set = AsyncMock()

    # Setup custom group mocking
    custom_group_mock = MagicMock()
    custom_data = {
        "author_id": 0,
        "content": "",
        "msg_id": 0,
        "status": "pending",
        "reason": None,
    }

    # Context manager mock for `async with self.config.custom(...)`
    class AsyncConfigContextManager:
        def __init__(self, data):
            self.data = data

        async def __aenter__(self):
            return self.data

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    custom_group_mock.all = MagicMock(return_value=AsyncConfigContextManager(custom_data))

    # Normal await mock for `await self.config.custom(...).all()`
    custom_group_mock_non_context = MagicMock()
    custom_group_mock_non_context.all = AsyncMock(return_value=custom_data.copy())

    # We need custom() to return the appropriate mock whether it's used as an async context manager or not
    def mock_custom(*args, **kwargs):
        # We'll use a wrapper that supports both
        class ConfigWrapper:
            def __init__(self, data):
                self._data = data

            def all(self):
                # We return an object that can be awaited AND used as an async context manager
                class AllWrapper:
                    def __init__(self, dict_data):
                        self._dict_data = dict_data

                    def __await__(self):
                        async def _get():
                            return self._dict_data.copy()

                        return _get().__await__()

                    async def __aenter__(self):
                        return self._dict_data

                    async def __aexit__(self, exc_type, exc_val, exc_tb):
                        pass

                return AllWrapper(self._data)

        return ConfigWrapper(custom_data)

    config_mock.custom = mock_custom
    cog_instance.config = config_mock

    # Load defaults
    await cog_instance.cog_load()
    return cog_instance


@pytest.fixture
def ctx_mock() -> Context:
    ctx = MagicMock(spec=Context)
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 12345
    ctx.send = AsyncMock()
    ctx.tick = AsyncMock()
    return ctx


@pytest.fixture
def interaction_mock() -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 54321
    interaction.user.display_name = "TestUser"
    interaction.user.display_avatar = MagicMock()
    interaction.user.display_avatar.url = "http://example.com/avatar.png"
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_get_suggestion_channel(cog: Suggest, bot_mock: MagicMock) -> None:
    channel_mock = MagicMock(spec=discord.TextChannel)
    bot_mock.get_channel.return_value = channel_mock

    result = await cog.get_suggestion_channel()

    bot_mock.get_channel.assert_called_once_with(SUGGEST_CHANNEL_ID)
    assert result is channel_mock


@pytest.mark.asyncio
async def test_get_suggestion_channel_not_text(cog: Suggest, bot_mock: MagicMock) -> None:
    bot_mock.get_channel.return_value = MagicMock(spec=discord.VoiceChannel)

    result = await cog.get_suggestion_channel()

    assert result is None


@pytest.mark.asyncio
async def test_process_new_suggestion_no_channel(
    cog: Suggest, bot_mock: MagicMock, interaction_mock: MagicMock
) -> None:
    bot_mock.get_channel.return_value = None

    await cog.process_new_suggestion(interaction_mock, "Make the bot cooler")

    interaction_mock.response.send_message.assert_called_once_with("Suggestion channel not found.", ephemeral=True)


@pytest.mark.asyncio
@patch("suggest.suggest.Suggest._maybe_repost_sticky")
async def test_process_new_suggestion_success(
    mock_repost: AsyncMock, cog: Suggest, bot_mock: MagicMock, interaction_mock: MagicMock
) -> None:
    channel_mock = AsyncMock(spec=discord.TextChannel)
    message_mock = MagicMock(spec=discord.Message)
    message_mock.id = 888888
    message_mock.add_reaction = AsyncMock()
    channel_mock.send = AsyncMock(return_value=message_mock)
    bot_mock.get_channel.return_value = channel_mock

    # Run
    await cog.process_new_suggestion(interaction_mock, "Make the bot cooler")

    # Verify increments
    cog.config.next_id.set.assert_called_once_with(133)  # type: ignore[attr-defined]

    # Verify send
    channel_mock.send.assert_called_once()
    _, kwargs = channel_mock.send.call_args
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert embed.title == "Suggestion #132"
    assert embed.description == "Make the bot cooler"

    # Verify reactions
    assert message_mock.add_reaction.call_count == 2

    # Verify response
    interaction_mock.response.send_message.assert_called_once_with("Suggestion submitted!", ephemeral=True)

    # Verify sticky triggered
    mock_repost.assert_called_once_with(channel_mock)


@pytest.mark.asyncio
async def test_approve_suggestion_not_found_config(cog: Suggest, ctx_mock: MagicMock) -> None:
    # If the custom config data is at defaults, msg_id is 0
    # The mock defaults to msg_id = 0
    await getattr(cog.approve, "callback")(cog, ctx_mock, 132)  # noqa: B009

    ctx_mock.send.assert_called_once_with("Suggestion not found.")


@pytest.mark.asyncio
async def test_approve_suggestion_already_approved(cog: Suggest, ctx_mock: MagicMock) -> None:
    # Setup the mock so the config says it's already approved
    custom_data = {"msg_id": 888, "status": "approved"}

    class ConfigWrapper:
        def all(self):
            class AllWrapper:
                def __await__(self):
                    async def _get():
                        return custom_data

                    return _get().__await__()

            return AllWrapper()

    cog.config.custom = MagicMock(return_value=ConfigWrapper())

    await getattr(cog.approve, "callback")(cog, ctx_mock, 132)  # noqa: B009

    ctx_mock.send.assert_called_once_with("Suggestion is already approved.")


@pytest.mark.asyncio
async def test_approve_suggestion_missing_channel(cog: Suggest, ctx_mock: MagicMock, bot_mock: MagicMock) -> None:
    custom_data = {"msg_id": 888, "status": "pending"}

    class ConfigWrapper:
        def all(self):
            class AllWrapper:
                def __await__(self):
                    async def _get():
                        return custom_data

                    return _get().__await__()

            return AllWrapper()

    cog.config.custom = MagicMock(return_value=ConfigWrapper())
    bot_mock.get_channel.return_value = None

    await getattr(cog.approve, "callback")(cog, ctx_mock, 132)  # noqa: B009

    ctx_mock.send.assert_called_once_with("Suggestion channel not found.")


@pytest.mark.asyncio
async def test_approve_suggestion_success(cog: Suggest, ctx_mock: MagicMock, bot_mock: MagicMock) -> None:
    custom_data = {"msg_id": 888, "status": "pending", "author_id": 54321}

    # We need the config mock to support await and async with
    class ConfigWrapper:
        def all(self):
            class AllWrapper:
                def __init__(self):
                    self.data = custom_data

                def __await__(self):
                    async def _get():
                        return self.data.copy()

                    return _get().__await__()

                async def __aenter__(self):
                    return self.data

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

            return AllWrapper()

    cog.config.custom = MagicMock(return_value=ConfigWrapper())

    channel_mock = AsyncMock(spec=discord.TextChannel)
    bot_mock.get_channel.return_value = channel_mock

    msg_mock = AsyncMock(spec=discord.Message)
    embed_mock = MagicMock(spec=discord.Embed)
    msg_mock.embeds = [embed_mock]

    user_mock = AsyncMock(spec=discord.User)
    bot_mock.fetch_user.return_value = user_mock

    # Mock reactions
    r1 = MagicMock(spec=discord.Reaction)
    r1.emoji = discord.PartialEmoji(name="up", id=UP_EMOJI_ID)
    r1.count = 3
    r1.me = True  # Bot voted, subtract 1

    r2 = MagicMock(spec=discord.Reaction)
    r2.emoji = discord.PartialEmoji(name="down", id=DOWN_EMOJI_ID)
    r2.count = 5
    r2.me = False  # Bot didn't vote (somehow), don't subtract

    msg_mock.reactions = [r1, r2]

    # Setup up/down emojis to match reactions above
    bot_mock.get_emoji.side_effect = lambda emoji_id: str(emoji_id)

    channel_mock.fetch_message.return_value = msg_mock

    # Run
    await getattr(cog.approve, "callback")(cog, ctx_mock, 132, reason="Great idea.")  # noqa: B009

    # Verify fetched
    channel_mock.fetch_message.assert_called_once_with(888)

    # Verify embed edited
    msg_mock.edit.assert_called_once()
    _, kwargs = msg_mock.edit.call_args
    assert "embed" in kwargs
    changed_embed = kwargs["embed"]
    assert changed_embed.color == discord.Color.green()
    assert changed_embed.title == "Approved Suggestion #132"
    changed_embed.add_field.assert_any_call(name="Reason", value="Great idea.", inline=False)

    # Verify stats
    # Upcount: 3 - 1 (me=True) = 2
    # Downcount: 5 - 0 (me=False) = 5
    changed_embed.add_field.assert_any_call(name="Results", value=f"{UP_EMOJI_ID} 2 - 5 {DOWN_EMOJI_ID}", inline=False)

    # Verify tick
    ctx_mock.tick.assert_called_once()

    # Verify config updated
    assert custom_data["status"] == "approved"
    assert custom_data["reason"] == "Great idea."

    # Verify DM
    user_mock.send.assert_called_once_with("Your suggestion #132 has been approved!\nReason: Great idea.")


@pytest.mark.asyncio
async def test_on_reaction_add_ignores_bots(cog: Suggest) -> None:
    reaction_mock = MagicMock(spec=discord.Reaction)
    user_mock = MagicMock(spec=discord.Member)
    user_mock.bot = True

    await cog.on_reaction_add(reaction_mock, user_mock)

    # No changes should happen
    assert not reaction_mock.message.channel.id.called


@pytest.mark.asyncio
async def test_on_reaction_add_wrong_channel(cog: Suggest) -> None:
    reaction_mock = MagicMock(spec=discord.Reaction)
    reaction_mock.message.channel.id = 1111111
    user_mock = MagicMock(spec=discord.Member)
    user_mock.bot = False

    await cog.on_reaction_add(reaction_mock, user_mock)

    # It should return early instead of checking emoji or looping
    # To test this, we ensure no further accesses were made
    assert "emoji" not in [c[0] for c in reaction_mock.mock_calls]


@pytest.mark.asyncio
async def test_on_reaction_add_mutually_exclusive(cog: Suggest) -> None:
    # Suppose user reacted UP. We want to clear their DOWN reaction.
    reaction_mock = MagicMock(spec=discord.Reaction)

    up_emoji = discord.PartialEmoji(name="up", id=UP_EMOJI_ID)
    reaction_mock.emoji = up_emoji

    user_mock = MagicMock(spec=discord.Member)
    user_mock.bot = False
    user_mock.id = 555

    # Message has both reactions
    msg_mock = MagicMock(spec=discord.Message)
    msg_mock.channel.id = SUGGEST_CHANNEL_ID
    reaction_mock.message = msg_mock

    down_reaction = AsyncMock(spec=discord.Reaction)
    down_emoji = discord.PartialEmoji(name="down", id=DOWN_EMOJI_ID)
    down_reaction.emoji = down_emoji

    # Setup users for the DOWN reaction to include our user
    async def _async_gen():
        yield user_mock

    down_reaction.users = MagicMock(return_value=_async_gen())

    msg_mock.reactions = [reaction_mock, down_reaction]

    # Run
    await cog.on_reaction_add(reaction_mock, user_mock)

    # The down reaction should be removed for this user
    down_reaction.remove.assert_called_once_with(user_mock)


@pytest.mark.asyncio
async def test_modal_submission(cog: Suggest, interaction_mock: MagicMock) -> None:
    # Test that the modal calls the right cog method
    modal = SuggestionModal(cog)

    # Mock the TextInput value since it's a property
    mock_input = MagicMock()
    mock_input.value = "More pizza"
    modal.suggestion_input = mock_input  # type: ignore[assignment]

    cog.process_new_suggestion = AsyncMock()

    await modal.on_submit(interaction_mock)

    cog.process_new_suggestion.assert_called_once_with(interaction_mock, "More pizza")


@pytest.mark.asyncio
async def test_sticky_view_button(cog: Suggest, interaction_mock: MagicMock) -> None:
    view = StickyView(cog)

    await view.suggest_button.callback(interaction_mock)  # type: ignore[call-arg]

    interaction_mock.response.send_modal.assert_called_once()
    args, _ = interaction_mock.response.send_modal.call_args
    assert isinstance(args[0], SuggestionModal)


# ---------------------------------------------------------------------------
# 6.5 — identifier serialization, shape validation, Unicode fallbacks
# ---------------------------------------------------------------------------


def _custom_wrapper(custom_data: dict):
    class ConfigWrapper:
        def all(self):
            class AllWrapper:
                def __await__(self):
                    async def _get():
                        return custom_data.copy()

                    return _get().__await__()

                async def __aenter__(self):
                    return custom_data

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass

            return AllWrapper()

    return ConfigWrapper()


@pytest.mark.asyncio
async def test_concurrent_suggestions_get_distinct_ids(cog: Suggest, bot_mock: MagicMock) -> None:
    """Two concurrent submissions receive distinct monotonically allocated IDs."""
    channel_mock = MagicMock(spec=discord.TextChannel)
    channel_mock.guild = MagicMock(spec=discord.Guild)
    channel_mock.guild.id = 1

    sent_embeds = []

    async def _send(**kwargs):
        sent_embeds.append(kwargs["embed"])
        msg = MagicMock(spec=discord.Message)
        msg.id = 900000 + len(sent_embeds)
        msg.add_reaction = AsyncMock()
        return msg

    channel_mock.send = _send
    bot_mock.get_channel.return_value = channel_mock
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    # Stateful next_id emulating Config persistence under the allocation lock
    state = {"next": 132}
    next_id_mock = AsyncMock(side_effect=lambda: state["next"])
    next_id_mock.set = AsyncMock(side_effect=lambda v: state.__setitem__("next", v))
    cog.config.next_id = next_id_mock  # type: ignore[attr-defined]

    def _interaction(user_id: int) -> MagicMock:
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock(spec=discord.Member)
        interaction.user.id = user_id
        interaction.user.display_name = f"User{user_id}"
        interaction.user.display_avatar = MagicMock()
        interaction.user.display_avatar.url = "http://example.com/a.png"
        interaction.response = MagicMock()
        interaction.response.send_message = AsyncMock()
        return interaction

    await asyncio.gather(
        cog.process_new_suggestion(_interaction(1), "first"),
        cog.process_new_suggestion(_interaction(2), "second"),
    )

    assert len(sent_embeds) == 2
    titles = sorted(e.title for e in sent_embeds)
    assert titles == ["Suggestion #132", "Suggestion #133"]
    # next_id advanced exactly twice
    assert next_id_mock.set.call_count == 2
    # Idle lock registry entry cleaned up
    assert cog._id_locks == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_msg_id", [None, 0, "junk", True], ids=repr)
async def test_resolve_malformed_msg_id_is_safe(cog: Suggest, ctx_mock: MagicMock, bad_msg_id: object) -> None:
    """Malformed persisted msg_id yields a safe 'not found' response."""
    custom_data = {"msg_id": bad_msg_id, "status": "pending"}
    cog.config.custom = MagicMock(return_value=_custom_wrapper(custom_data))

    await getattr(cog.approve, "callback")(cog, ctx_mock, 132)  # noqa: B009

    ctx_mock.send.assert_called_once_with("Suggestion not found.")


@pytest.mark.asyncio
async def test_resolve_malformed_status_is_safe(cog: Suggest, ctx_mock: MagicMock) -> None:
    """A non-string persisted status is reported as malformed, record untouched."""
    custom_data = {"msg_id": 888, "status": 42}
    cog.config.custom = MagicMock(return_value=_custom_wrapper(custom_data))

    await getattr(cog.approve, "callback")(cog, ctx_mock, 132)  # noqa: B009

    assert "malformed" in ctx_mock.send.call_args[0][0]
    assert custom_data["status"] == 42  # unchanged


@pytest.mark.asyncio
async def test_resolve_message_without_embed_is_safe(cog: Suggest, ctx_mock: MagicMock, bot_mock: MagicMock) -> None:
    """A suggestion message missing its embed fails safely, record unchanged."""
    custom_data = {"msg_id": 888, "status": "pending", "author_id": 1}
    cog.config.custom = MagicMock(return_value=_custom_wrapper(custom_data))

    channel_mock = AsyncMock(spec=discord.TextChannel)
    bot_mock.get_channel.return_value = channel_mock

    msg_mock = AsyncMock(spec=discord.Message)
    msg_mock.embeds = []
    channel_mock.fetch_message.return_value = msg_mock

    await getattr(cog.approve, "callback")(cog, ctx_mock, 132)  # noqa: B009

    assert "missing its embed" in ctx_mock.send.call_args[0][0]
    assert custom_data["status"] == "pending"  # unchanged


@pytest.mark.asyncio
async def test_on_reaction_add_unicode_fallback_mutually_exclusive(cog: Suggest) -> None:
    """Unicode fallback reactions enforce the same mutual-exclusion behavior."""
    reaction_mock = MagicMock(spec=discord.Reaction)
    reaction_mock.emoji = "✅"  # Unicode fallback up-vote

    user_mock = MagicMock(spec=discord.Member)
    user_mock.bot = False
    user_mock.id = 555

    msg_mock = MagicMock(spec=discord.Message)
    msg_mock.channel.id = SUGGEST_CHANNEL_ID
    reaction_mock.message = msg_mock

    down_reaction = AsyncMock(spec=discord.Reaction)
    down_reaction.emoji = "❌"  # Unicode fallback down-vote

    async def _async_gen():
        yield user_mock

    down_reaction.users = MagicMock(return_value=_async_gen())
    msg_mock.reactions = [reaction_mock, down_reaction]

    await cog.on_reaction_add(reaction_mock, user_mock)

    down_reaction.remove.assert_called_once_with(user_mock)


@pytest.mark.parametrize(
    "emoji, expected",
    [
        (discord.PartialEmoji(name="up", id=UP_EMOJI_ID), "up"),
        (discord.PartialEmoji(name="down", id=DOWN_EMOJI_ID), "down"),
        ("✅", "up"),
        ("❌", "down"),
        ("🍕", None),
        (discord.PartialEmoji(name="other", id=1), None),
    ],
    ids=["custom_up", "custom_down", "unicode_up", "unicode_down", "unicode_other", "custom_other"],
)
def test_vote_emoji_kind(emoji: object, expected: str | None) -> None:
    from suggest.suggest import vote_emoji_kind

    assert vote_emoji_kind(emoji) == expected
