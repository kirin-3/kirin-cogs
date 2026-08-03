"""Unit and dpytest integration tests for the Profile cog."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from profile.profile import Profile
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config
from redbot.core.bot import Red


def _make_config_attr(value: object) -> AsyncMock:
    attr = AsyncMock(return_value=value)
    attr.set = AsyncMock()
    return attr


def _make_profile_config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.register_global = MagicMock()
    config.register_guild = MagicMock()
    config.register_member = MagicMock()
    config.register_user = MagicMock()

    # Legacy global accessors (read by lazy per-guild adoption)
    config.schema_version = _make_config_attr(0)
    config.channel_id = _make_config_attr(686091267012296714)
    config.sticky_message_id = _make_config_attr(None)
    config.sticky_locked = _make_config_attr(False)
    config.cooldown = _make_config_attr(0)

    # Guild-scoped configuration; adoption skipped by default in unit tests
    guild_group = MagicMock()
    guild_group.channel_id = _make_config_attr(None)
    guild_group.sticky_message_id = _make_config_attr(None)
    guild_group.cooldown = _make_config_attr(3)
    guild_group.legacy_adopted = _make_config_attr(True)
    config.guild = MagicMock(return_value=guild_group)

    # Member-scoped profile records
    member_group = MagicMock()
    member_group.all = AsyncMock(return_value={"profile_data": {}, "message_id": None, "last_delete": None})
    member_group.profile_data = _make_config_attr({})
    member_group.message_id = _make_config_attr(None)
    member_group.last_delete = _make_config_attr(None)
    member_group.clear = AsyncMock()
    config.member = MagicMock(return_value=member_group)

    config.all_users = AsyncMock(return_value={})
    return config


def _make_guild(guild_id: int = 1) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    return guild


def _make_member(member_id: int = 123) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.display_name = "Tester"
    member.mention = f"<@{member_id}>"
    member.color = discord.Color.blue()

    avatar = MagicMock()
    avatar.url = "https://example.com/avatar.png"
    member.display_avatar = avatar
    return member


def _make_interaction(member: MagicMock, guild: discord.Guild | None = None) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = member
    interaction.guild = guild
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.add_view = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.is_owner = AsyncMock(return_value=False)
    return bot


@pytest.fixture
def config_mock() -> MagicMock:
    return _make_profile_config_mock()


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, config_mock: MagicMock) -> Profile:
    with patch("profile.profile.Config.get_conf", return_value=config_mock):
        profile_cog = Profile(bot_mock)
    profile_cog.config = config_mock
    return profile_cog


@pytest.mark.asyncio
async def test_get_profile_channel_returns_text_channel(
    cog: Profile, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 111
    bot_mock.get_channel.return_value = channel
    config_mock.guild.return_value.channel_id = AsyncMock(return_value=111)

    result = await cog.get_profile_channel(_make_guild())
    assert result is channel


@pytest.mark.asyncio
async def test_get_profile_channel_returns_none_for_non_text(
    cog: Profile, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    bot_mock.get_channel.return_value = object()
    config_mock.guild.return_value.channel_id = AsyncMock(return_value=111)

    result = await cog.get_profile_channel(_make_guild())
    assert result is None


@pytest.mark.asyncio
async def test_handle_create_edit_blocks_on_24h_cooldown(
    cog: Profile, config_mock: MagicMock, bot_mock: MagicMock
) -> None:
    member = _make_member()
    interaction = _make_interaction(member, guild=MagicMock(spec=discord.Guild))

    recent_delete = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    config_mock.member.return_value.all = AsyncMock(
        return_value={"profile_data": {}, "message_id": None, "last_delete": recent_delete}
    )
    bot_mock.is_owner = AsyncMock(return_value=False)

    await cog.handle_create_edit(interaction)

    interaction.response.send_message.assert_awaited_once()
    assert "must wait 24 hours" in interaction.response.send_message.call_args[0][0]
    assert interaction.response.send_message.call_args[1]["ephemeral"] is True
    interaction.followup.send.assert_not_called()


@pytest.mark.asyncio
async def test_handle_create_edit_submitted_updates_profile(cog: Profile, config_mock: MagicMock) -> None:
    member = _make_member()
    interaction = _make_interaction(member, guild=MagicMock(spec=discord.Guild))

    config_mock.member.return_value.all = AsyncMock(
        return_value={"profile_data": {}, "message_id": None, "last_delete": None}
    )

    fake_view = MagicMock()
    fake_view.wait = AsyncMock()
    fake_view.submitted = True
    fake_view.data = {"name": "Alice", "age": 28}

    cog._update_profile_embed = AsyncMock()  # type: ignore[method-assign]

    with patch("profile.profile.ProfileBuilderView", return_value=fake_view):
        await cog.handle_create_edit(interaction)

    config_mock.member.return_value.profile_data.set.assert_awaited_once_with(fake_view.data)
    cog._update_profile_embed.assert_awaited_once_with(member, fake_view.data)
    interaction.followup.send.assert_awaited_once_with("Profile updated successfully!", ephemeral=True)


@pytest.mark.asyncio
async def test_handle_delete_request_without_profile(cog: Profile, config_mock: MagicMock) -> None:
    member = _make_member()
    interaction = _make_interaction(member, guild=MagicMock(spec=discord.Guild))
    config_mock.member.return_value.all = AsyncMock(
        return_value={"profile_data": {}, "message_id": None, "last_delete": None}
    )

    await cog.handle_delete_request(interaction)

    interaction.response.send_message.assert_awaited_once_with("You don't have a profile to delete.", ephemeral=True)


@pytest.mark.asyncio
async def test_handle_delete_request_confirmed_deletes_message(cog: Profile, config_mock: MagicMock) -> None:
    member = _make_member()
    interaction = _make_interaction(member, guild=MagicMock(spec=discord.Guild))
    config_mock.member.return_value.all = AsyncMock(
        return_value={"profile_data": {"name": "Alice"}, "message_id": 999, "last_delete": None}
    )

    channel = MagicMock(spec=discord.TextChannel)
    message = MagicMock(spec=discord.Message)
    message.delete = AsyncMock()
    channel.get_partial_message.return_value = message
    cog.get_profile_channel = AsyncMock(return_value=channel)  # type: ignore[method-assign]

    fake_view = MagicMock()
    fake_view.wait = AsyncMock()
    fake_view.value = True

    with patch("profile.profile.ProfileDeleteConfirmView", return_value=fake_view):
        await cog.handle_delete_request(interaction)

    message.delete.assert_awaited_once()
    config_mock.member.return_value.clear.assert_awaited_once()
    config_mock.member.return_value.last_delete.set.assert_awaited_once()
    interaction.followup.send.assert_awaited_once_with("Your profile has been deleted.", ephemeral=True)


@pytest.mark.asyncio
async def test_update_profile_embed_edits_existing_message(cog: Profile, config_mock: MagicMock) -> None:
    member = _make_member()
    channel = MagicMock(spec=discord.TextChannel)
    message = MagicMock(spec=discord.Message)
    message.edit = AsyncMock()
    channel.get_partial_message.return_value = message

    cog.get_profile_channel = AsyncMock(return_value=channel)  # type: ignore[method-assign]
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    config_mock.member.return_value.message_id = AsyncMock(return_value=456)
    config_mock.member.return_value.message_id.set = AsyncMock()

    await cog._update_profile_embed(member, {"name": "Alice", "age": 28})

    message.edit.assert_awaited_once()
    channel.send.assert_not_called()
    cog._maybe_repost_sticky.assert_not_called()


@pytest.mark.asyncio
async def test_update_profile_embed_sends_new_message_when_no_existing(cog: Profile, config_mock: MagicMock) -> None:
    member = _make_member()
    channel = MagicMock(spec=discord.TextChannel)
    new_message = MagicMock(spec=discord.Message)
    new_message.id = 789
    channel.send = AsyncMock(return_value=new_message)

    cog.get_profile_channel = AsyncMock(return_value=channel)  # type: ignore[method-assign]
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    config_mock.member.return_value.message_id = AsyncMock(return_value=None)
    config_mock.member.return_value.message_id.set = AsyncMock()

    await cog._update_profile_embed(member, {"name": "Alice", "age": 28})

    channel.send.assert_awaited_once()
    config_mock.member.return_value.message_id.set.assert_awaited_once_with(789)
    cog._maybe_repost_sticky.assert_awaited_once_with(member.guild, channel)


@pytest.mark.asyncio
async def test_maybe_repost_sticky_skips_wrong_channel_when_no_sticky(cog: Profile, config_mock: MagicMock) -> None:
    guild = _make_guild()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    channel.last_message_id = None

    config_mock.guild.return_value.sticky_message_id = AsyncMock(return_value=None)
    config_mock.guild.return_value.channel_id = AsyncMock(return_value=999)
    cog._do_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    await cog._maybe_repost_sticky(guild, channel)

    cog._do_repost_sticky.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_repost_sticky_reposts_when_no_sticky(cog: Profile, config_mock: MagicMock) -> None:
    guild = _make_guild()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    channel.last_message_id = None

    config_mock.guild.return_value.sticky_message_id = AsyncMock(return_value=None)
    config_mock.guild.return_value.channel_id = AsyncMock(return_value=123)
    cog._do_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    await cog._maybe_repost_sticky(guild, channel)

    cog._do_repost_sticky.assert_awaited_once()


@pytest.mark.asyncio
async def test_maybe_repost_sticky_skips_when_responding_to_sticky(cog: Profile, config_mock: MagicMock) -> None:
    sticky_id = 190000000000000000

    guild = _make_guild()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    channel.last_message_id = None

    responding = MagicMock(spec=discord.Message)
    responding.id = sticky_id

    config_mock.guild.return_value.sticky_message_id = AsyncMock(return_value=sticky_id)
    config_mock.guild.return_value.cooldown = AsyncMock(return_value=0)
    cog._do_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    await cog._maybe_repost_sticky(guild, channel, responding_to_message=responding)

    cog._do_repost_sticky.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_repost_sticky_skips_when_already_last_message(cog: Profile, config_mock: MagicMock) -> None:
    sticky_id = 190000000000000000

    guild = _make_guild()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    channel.last_message_id = sticky_id

    config_mock.guild.return_value.sticky_message_id = AsyncMock(return_value=sticky_id)
    config_mock.guild.return_value.cooldown = AsyncMock(return_value=0)
    cog._do_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    await cog._maybe_repost_sticky(guild, channel)

    cog._do_repost_sticky.assert_not_called()


@pytest.mark.asyncio
async def test_do_repost_sticky_deletes_old_and_sets_new_id(cog: Profile, config_mock: MagicMock) -> None:
    guild = _make_guild()
    channel = MagicMock(spec=discord.TextChannel)

    old_message = MagicMock(spec=discord.Message)
    old_message.delete = AsyncMock()
    channel.get_partial_message.return_value = old_message

    new_message = MagicMock(spec=discord.Message)
    new_message.id = 654
    channel.send = AsyncMock(return_value=new_message)

    config_mock.guild.return_value.sticky_message_id = AsyncMock(return_value=321)
    config_mock.guild.return_value.sticky_message_id.set = AsyncMock()

    cv = asyncio.Condition()
    async with cv:
        await cog._do_repost_sticky(guild, channel, cv)

    old_message.delete.assert_awaited_once()
    channel.send.assert_awaited_once()
    config_mock.guild.return_value.sticky_message_id.set.assert_awaited_once_with(654)
    assert channel not in cog.locked_channels


@pytest.mark.asyncio
async def test_on_message_calls_maybe_repost_for_profile_channel(cog: Profile, config_mock: MagicMock) -> None:
    guild = _make_guild()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.guild = guild
    message.channel = channel

    config_mock.guild.return_value.channel_id = AsyncMock(return_value=123)
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    await cog.on_message(message)

    cog._maybe_repost_sticky.assert_awaited_once_with(guild, channel, responding_to_message=message)


@pytest.mark.asyncio
async def test_on_raw_message_delete_reposts_when_sticky_deleted(
    cog: Profile, config_mock: MagicMock, bot_mock: MagicMock
) -> None:
    guild = _make_guild()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    bot_mock.get_guild = MagicMock(return_value=guild)
    bot_mock.get_channel.return_value = channel

    payload = MagicMock(spec=discord.RawMessageDeleteEvent)
    payload.guild_id = guild.id
    payload.channel_id = 123
    payload.message_id = 456

    config_mock.guild.return_value.channel_id = AsyncMock(return_value=123)
    config_mock.guild.return_value.sticky_message_id = AsyncMock(return_value=456)
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    await cog.on_raw_message_delete(payload)

    cog._maybe_repost_sticky.assert_awaited_once_with(guild, channel)


@pytest_asyncio.fixture
async def dpytest_bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.message_content = True

    bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(bot)

    yield bot

    await dpytest.empty_queue()


@pytest.mark.asyncio
async def test_dpytest_on_message_dispatches_profile_listener(dpytest_bot: dpy_commands.Bot) -> None:
    config_mock = _make_profile_config_mock()
    channel_id = dpytest.get_config().channels[0].id
    config_mock.guild.return_value.channel_id = AsyncMock(return_value=channel_id)

    with patch("profile.profile.Config.get_conf", return_value=config_mock):
        cog = Profile(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    await dpytest_bot.add_cog(cog)

    await dpytest.message("hello profile channel")
    await dpytest.run_all_events()
    await dpytest.empty_queue()

    cog._maybe_repost_sticky.assert_awaited_once()
