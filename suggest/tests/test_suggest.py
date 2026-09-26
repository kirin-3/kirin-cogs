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
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
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

    # Acknowledged before posting, confirmed after
    interaction_mock.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction_mock.followup.send.assert_awaited_once_with("Suggestion submitted!", ephemeral=True)

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
        interaction.response.defer = AsyncMock()
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()
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


@pytest.mark.parametrize(
    "emoji, expected",
    [
        (discord.PartialEmoji(name="up", id=UP_EMOJI_ID), "up"),
        (discord.PartialEmoji(name="down", id=DOWN_EMOJI_ID), "down"),
        ("✅", "up"),
        ("❌", "down"),
        ("🍕", None),
        (discord.PartialEmoji(name="other", id=1), None),
        (discord.PartialEmoji(name="✅"), "up"),
        (discord.PartialEmoji(name="❌"), "down"),
    ],
    ids=[
        "custom_up",
        "custom_down",
        "unicode_up",
        "unicode_down",
        "unicode_other",
        "custom_other",
        "raw_up",
        "raw_down",
    ],
)
def test_vote_emoji_kind(emoji: object, expected: str | None) -> None:
    from suggest.suggest import vote_emoji_kind

    assert vote_emoji_kind(emoji) == expected


def _raw_vote(
    emoji: discord.PartialEmoji, *, user_id: int = 555, bot: bool = False, channel_id: int = SUGGEST_CHANNEL_ID
):
    payload = MagicMock(spec=discord.RawReactionActionEvent)
    payload.channel_id = channel_id
    payload.message_id = 777
    payload.user_id = user_id
    payload.emoji = emoji
    payload.member = MagicMock(spec=discord.Member, bot=bot)
    return payload


def _voted_message(*emojis: object) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.id = 777
    msg.reactions = [MagicMock(spec=discord.Reaction, emoji=e) for e in emojis]
    msg.remove_reaction = AsyncMock()
    return msg


UP = discord.PartialEmoji(name="up", id=UP_EMOJI_ID)
DOWN = discord.PartialEmoji(name="down", id=DOWN_EMOJI_ID)


@pytest.mark.asyncio
async def test_raw_vote_on_uncached_message_fetches_and_removes_the_opposite_vote(
    cog: Suggest, bot_mock: MagicMock
) -> None:
    msg = _voted_message(UP, DOWN, "❌")  # custom and fallback down-votes on an older suggestion
    channel = MagicMock(spec=discord.TextChannel)
    channel.fetch_message = AsyncMock(return_value=msg)
    bot_mock.get_channel.return_value = channel
    bot_mock.cached_messages = []  # e.g. after a restart

    await cog.on_raw_reaction_add(_raw_vote(UP))

    channel.fetch_message.assert_awaited_once_with(777)
    removed = [(c.args[0], c.args[1].id) for c in msg.remove_reaction.await_args_list]
    assert removed == [(DOWN, 555), ("❌", 555)]


@pytest.mark.asyncio
async def test_raw_unicode_vote_uses_the_cached_message(cog: Suggest, bot_mock: MagicMock) -> None:
    msg = _voted_message("✅", "❌")
    channel = MagicMock(spec=discord.TextChannel)
    channel.fetch_message = AsyncMock()
    bot_mock.get_channel.return_value = channel
    bot_mock.cached_messages = [msg]

    await cog.on_raw_reaction_add(_raw_vote(discord.PartialEmoji(name="❌")))

    channel.fetch_message.assert_not_awaited()
    assert [c.args[0] for c in msg.remove_reaction.await_args_list] == ["✅"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        _raw_vote(UP, bot=True),
        _raw_vote(UP, channel_id=1111111),
        _raw_vote(discord.PartialEmoji(name="🍕")),
    ],
    ids=["bot", "other_channel", "not_a_vote"],
)
async def test_raw_vote_ignores_bots_other_channels_and_other_emoji(
    cog: Suggest, bot_mock: MagicMock, payload: MagicMock
) -> None:
    await cog.on_raw_reaction_add(payload)
    bot_mock.get_channel.assert_not_called()


@pytest.mark.asyncio
async def test_failed_post_is_reported_after_deferring(
    cog: Suggest, bot_mock: MagicMock, interaction_mock: MagicMock
) -> None:
    channel_mock = AsyncMock(spec=discord.TextChannel)
    channel_mock.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no"))
    bot_mock.get_channel.return_value = channel_mock

    await cog.process_new_suggestion(interaction_mock, "Make the bot cooler")

    interaction_mock.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction_mock.followup.send.assert_awaited_once_with(
        "I couldn't post your suggestion. Please try again.", ephemeral=True
    )
