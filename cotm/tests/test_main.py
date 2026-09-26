"""Integration and unit tests for ContestCog in cotm/main.py"""

import asyncio
import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import commands

from cotm import const
from cotm.main import ContestCog


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock) -> ContestCog:
    cog = ContestCog(bot_mock)
    # Red's test config is shared across tests, so saved contest results would leak between them
    await cog.config.payouts.clear()
    await cog.config.dashboards.clear()
    return cog


@pytest.fixture
def ctx_mock() -> MagicMock:
    ctx = MagicMock(spec=commands.Context)
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.send = AsyncMock()
    ctx.send = AsyncMock()
    # async with ctx.typing() must work as an async context manager
    typing_cm = MagicMock()
    typing_cm.__aenter__ = AsyncMock(return_value=None)
    typing_cm.__aexit__ = AsyncMock(return_value=False)
    ctx.typing = MagicMock(return_value=typing_cm)
    return ctx


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_contest_info(cog: ContestCog, ctx_mock: MagicMock) -> None:
    cog._import_txt = MagicMock(return_value="test text")  # type: ignore[method-assign]
    cog._format_text = MagicMock(return_value="formatted text")  # type: ignore[method-assign]
    ctx_mock.channel.send.return_value = SimpleNamespace(id=4242)

    await cog.contest.callback(cog, ctx_mock, 5)  # type: ignore[arg-type]

    assert cog.contest_number == "5th"

    cast(AsyncMock, ctx_mock.channel.send).assert_called_once()
    _args, kwargs = ctx_mock.channel.send.call_args
    assert "view" in kwargs

    view = kwargs["view"]
    from cotm.cotm_views import ContestDashboardView

    assert isinstance(view, ContestDashboardView)
    assert view.texts["description"] == "formatted text"

    # contest_number must be persisted to Config
    saved = await cog.config.contest_number()
    assert saved == 5
    assert await cog.config.dashboards() == {"4242": 5}


@pytest.mark.asyncio
async def test_post_contest_info_no_number_skips_config_save(cog: ContestCog, ctx_mock: MagicMock) -> None:
    """Calling [p]contest without a number does not overwrite the saved contest_number."""
    await cog.config.contest_number.set(3)

    cog._import_txt = MagicMock(return_value="")  # type: ignore[method-assign]
    cog._format_text = MagicMock(return_value="")  # type: ignore[method-assign]

    await cog.contest.callback(cog, ctx_mock, None)  # type: ignore[arg-type]

    saved = await cog.config.contest_number()
    assert saved == 3  # unchanged


@pytest.mark.asyncio
async def test_cog_load_restores_number_and_registers_view(cog: ContestCog, bot_mock: MagicMock) -> None:
    """cog_load reads contest_number from Config and registers a persistent ContestDashboardView."""
    await cog.config.contest_number.set(7)

    cog._import_txt = MagicMock(return_value="")  # type: ignore[method-assign]
    cog._format_text = MagicMock(return_value="")  # type: ignore[method-assign]

    await cog.cog_load()

    assert cog._contest_number == 7

    bot_mock.add_view.assert_called_once()
    view_arg = bot_mock.add_view.call_args[0][0]
    from cotm.cotm_views import ContestDashboardView

    assert isinstance(view_arg, ContestDashboardView)


@pytest.mark.asyncio
async def test_cog_load_binds_recorded_dashboards_to_their_contest(cog: ContestCog, bot_mock: MagicMock) -> None:
    """A dashboard posted for an older contest keeps that contest after a restart."""
    await cog.config.contest_number.set(7)
    await cog.config.dashboards.set({"1001": 6, "junk": 5, "1002": None})
    cog._import_txt = MagicMock(return_value="{contest_number}")  # type: ignore[method-assign]

    await cog.cog_load()

    bound = [(c.args[0], c.kwargs.get("message_id")) for c in bot_mock.add_view.call_args_list]
    assert [(v.contest_number, mid) for v, mid in bound] == [(7, None), (6, 1001)]
    assert bound[1][0].texts["description"] == "6th"


@pytest.mark.asyncio
async def test_get_contest_results(cog: ContestCog) -> None:
    channel = MagicMock(spec=discord.TextChannel)

    msg1 = MagicMock(spec=discord.Message)
    # author must be a proper mock so str() returns a predictable string
    author_mock = MagicMock(spec=discord.Member)
    author_mock.__str__ = MagicMock(return_value="User1")
    msg1.author = author_mock

    react1 = MagicMock(spec=discord.Reaction)
    react1.emoji = const.COTM_VOTE_EMOJI

    user1 = MagicMock(spec=discord.Member)
    user1.joined_at = datetime.now(UTC) - timedelta(days=10)
    user2 = MagicMock(spec=discord.Member)
    user2.joined_at = datetime.now(UTC) - timedelta(days=2)

    async def get_users() -> AsyncGenerator[MagicMock, None]:
        yield user1
        yield user2

    react1.users.return_value = get_users()
    msg1.reactions = [react1]

    async def history(limit: int | None = None) -> AsyncGenerator[MagicMock, None]:
        yield msg1

    channel.history.return_value = history()

    # voter_server_age = 5 days: user1 (joined 10 days ago) is valid, user2 (joined 2 days ago) is not
    results = await cog._get_contest_results(channel, const.COTM_VOTE_EMOJI, timedelta(days=5))

    assert len(results) == 1
    assert results[0]["name"] == "User1"
    assert results[0]["valid_votes"] == 1
    assert results[0]["invalid_votes"] == 1


@pytest.mark.asyncio
async def test_contestcount(cog: ContestCog, ctx_mock: MagicMock) -> None:
    channel_mock = MagicMock(spec=discord.TextChannel)
    channel_mock.mention = "#test-channel"

    cog._get_contest_results = AsyncMock(  # type: ignore[method-assign]
        return_value=[{"name": "User1", "valid_votes": 5, "invalid_votes": 1}]
    )

    await cog.contestcount.callback(
        cog,  # type: ignore[arg-type]
        ctx_mock,
        channel_mock,
        const.COTM_VOTE_EMOJI,
        False,
        None,
    )

    cast(AsyncMock, ctx_mock.channel.send).assert_called_once()
    _args, kwargs = ctx_mock.channel.send.call_args
    assert "view" in kwargs
    from cotm.cotm_views import StandingsView

    assert isinstance(kwargs["view"], StandingsView)


@pytest.mark.asyncio
async def test_cotmreward(cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock) -> None:
    unicornia_mock = MagicMock()
    unicornia_mock.apply_operation = AsyncMock(return_value=SimpleNamespace(state="settled"))
    bot_mock.get_cog.return_value = unicornia_mock
    ctx_mock.guild = MagicMock(id=555)
    await cog.config.contest_number.set(4)
    cog._contest_number = 4

    channel_mock = MagicMock(spec=discord.TextChannel)
    channel_mock.id = 900
    channel_mock.mention = "#test-channel"

    msg1 = MagicMock(spec=discord.Message)
    user_author = MagicMock(spec=discord.Member)
    user_author.id = 123
    user_author.__str__ = MagicMock(return_value="User1")
    msg1.author = user_author

    react1 = MagicMock(spec=discord.Reaction)
    react1.emoji = const.COTM_VOTE_EMOJI

    voter = MagicMock(spec=discord.Member)
    voter.joined_at = datetime.now(UTC) - timedelta(days=10)

    async def get_users() -> AsyncGenerator[MagicMock, None]:
        yield voter

    react1.users.return_value = get_users()
    msg1.reactions = [react1]

    async def history(limit: int | None = None) -> AsyncGenerator[MagicMock, None]:
        yield msg1

    channel_mock.history.return_value = history()

    await cog.cotmreward.callback(
        cog,  # type: ignore[arg-type]
        ctx_mock,
        channel_mock,
    )

    unicornia_mock.apply_operation.assert_called_once_with(
        key="cotm:4:123",
        user_id=123,
        amount=const.COTM_REWARDS[0],
        direction="credit",
        source="ContestCog",
        guild_id=555,
        reason="COTM 4th Reward (Rank 1)",
    )

    cast(AsyncMock, ctx_mock.channel.send).assert_called_once()


# ---------------------------------------------------------------------------
# dpytest integration: verify the cog is loaded and bot responds to a message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dpytest_message_does_not_raise() -> None:
    """Sending a plain message through dpytest must not raise any errors.

    ContestCog has no on_message listener, but this confirms the cog attaches
    to the bot without breaking the event dispatch pipeline.

    Bot, cog, and dpytest setup are done inline to avoid fixture-scoping issues
    with dpytest's module-level _cur_config global state.
    """
    intents = discord.Intents.default()
    intents.members = True  # required for member cache so dpytest.message() works
    intents.messages = True
    intents.message_content = True
    intents.guilds = True

    bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(bot)

    cog = ContestCog(bot)  # type: ignore[arg-type]
    await bot.add_cog(cog)

    await dpytest.message("hello")
    await dpytest.run_all_events()
    await dpytest.empty_queue()
    # No exception means the cog attaches cleanly and event dispatch is intact.


# ---------------------------------------------------------------------------
# Tally, payout and standings regressions
# ---------------------------------------------------------------------------


def _person(user_id: int, name: str | None = None, *, member: bool = True) -> MagicMock:
    person = MagicMock(spec=discord.Member)
    person.id = user_id
    person.joined_at = datetime.now(UTC) - timedelta(days=30) if member else None
    person.__str__ = MagicMock(return_value=name or f"user{user_id}")
    return person


def _entry(author: MagicMock, votes: dict[str, list[MagicMock]]) -> MagicMock:
    """A message by `author` with the given voters per reaction emoji."""
    message = MagicMock(spec=discord.Message)
    message.author = author
    reactions = []
    for emoji, voters in votes.items():
        reaction = MagicMock(spec=discord.Reaction)
        reaction.emoji = emoji

        def users(voters: list[MagicMock] = voters) -> AsyncGenerator[MagicMock, None]:
            async def gen() -> AsyncGenerator[MagicMock, None]:
                for voter in voters:
                    yield voter

            return gen()

        reaction.users.side_effect = users
        reactions.append(reaction)
    message.reactions = reactions
    return message


def _channel(messages: list[MagicMock], channel_id: int = 900) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.mention = "#entries"

    def history(limit: int | None = None) -> AsyncGenerator[MagicMock, None]:
        async def gen() -> AsyncGenerator[MagicMock, None]:
            for message in messages:
                yield message

        return gen()

    channel.history.side_effect = history
    return channel


def _voters(count: int, start: int = 1000) -> list[MagicMock]:
    return [_person(start + i) for i in range(count)]


class _Ledger:
    """Unicornia stand-in whose apply_operation is idempotent per key, like the real one."""

    def __init__(self) -> None:
        self.paid: dict[str, tuple[int, int]] = {}
        self.calls: list[dict[str, Any]] = []

    async def apply_operation(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if kwargs["key"] in self.paid:
            return SimpleNamespace(state="duplicate")
        self.paid[kwargs["key"]] = (kwargs["user_id"], kwargs["amount"])
        return SimpleNamespace(state="settled")


def _payout_log(ctx: MagicMock) -> str:
    view = ctx.channel.send.call_args.kwargs["view"]
    container = view.children[0]
    return container.children[-1].content


@pytest.mark.asyncio
async def test_extra_vote_emojis_add_up_and_count_each_voter_once(cog: ContestCog) -> None:
    a, b, c = _person(1), _person(2), _person(3)
    channel = _channel([_entry(_person(10), {"💖": [a, b], "🌟": [b, c], "👎": [_person(4)]})])

    results = await cog._get_contest_results(channel, "💖", None, "🌟")

    assert results[0]["valid_votes"] == 3


@pytest.mark.asyncio
async def test_author_with_two_entries_is_ranked_once_by_best_entry(cog: ContestCog) -> None:
    twice, other = _person(10, "twice"), _person(20, "other")
    emote = const.COTM_VOTE_EMOJI
    channel = _channel(
        [
            _entry(twice, {emote: _voters(3)}),
            _entry(other, {emote: _voters(4, 2000)}),
            _entry(twice, {emote: _voters(5, 3000)}),
        ]
    )

    results = await cog._get_contest_results(channel)

    assert [(r["name"], r["valid_votes"]) for r in results] == [("twice", 5), ("other", 4)]


@pytest.mark.asyncio
async def test_cotmreward_twice_pays_each_winner_once(
    cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    ledger = _Ledger()
    bot_mock.get_cog.return_value = ledger
    ctx_mock.guild = MagicMock(id=555)
    cog._contest_number = 53
    emote = const.COTM_VOTE_EMOJI
    channel = _channel([_entry(_person(1), {emote: _voters(3)}), _entry(_person(2), {emote: _voters(2, 2000)})])

    await cog.cotmreward.callback(cog, ctx_mock, channel)  # type: ignore[arg-type]
    await cog.cotmreward.callback(cog, ctx_mock, channel)  # type: ignore[arg-type]

    assert ledger.paid == {"cotm:53:1": (1, const.COTM_REWARDS[0]), "cotm:53:2": (2, const.COTM_REWARDS[1])}
    assert len(ledger.calls) == 4
    assert _payout_log(ctx_mock).count("already paid") == 2


@pytest.mark.asyncio
async def test_cotmreward_same_person_cannot_take_two_places(
    cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    ledger = _Ledger()
    bot_mock.get_cog.return_value = ledger
    ctx_mock.guild = MagicMock(id=555)
    emote = const.COTM_VOTE_EMOJI
    twice = _person(1)
    channel = _channel(
        [
            _entry(twice, {emote: _voters(5)}),
            _entry(twice, {emote: _voters(4, 2000)}),
            _entry(_person(2), {emote: _voters(3, 3000)}),
        ]
    )

    await cog.cotmreward.callback(cog, ctx_mock, channel, 7)  # type: ignore[arg-type]

    assert ledger.paid == {"cotm:7:1": (1, const.COTM_REWARDS[0]), "cotm:7:2": (2, const.COTM_REWARDS[1])}


@pytest.mark.asyncio
async def test_cotmreward_pays_only_the_places_in_prizes(
    cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    ledger = _Ledger()
    bot_mock.get_cog.return_value = ledger
    ctx_mock.guild = MagicMock(id=555)
    emote = const.COTM_VOTE_EMOJI
    channel = _channel([_entry(_person(i), {emote: _voters(20 - i, 1000 * (i + 1))}) for i in range(12)])

    await cog.cotmreward.callback(cog, ctx_mock, channel)  # type: ignore[arg-type]

    assert [amount for _, amount in ledger.paid.values()] == const.COTM_REWARDS
    assert set(ledger.paid) == {f"cotm:1:{i}" for i in range(len(const.COTM_REWARDS))}


def test_rewards_match_the_places_listed_in_prizes() -> None:
    prizes = const.PRIZES_DESCRIPTION.read_text(encoding="utf-8")
    places = [int(n) for n in re.findall(r"(\d+)(?:st|nd|rd|th) Place", prizes)]
    places += [int(n) for n in re.findall(r"to (\d+)(?:st|nd|rd|th) Place", prizes)]

    assert max(places) == len(const.COTM_REWARDS) == 9


@pytest.mark.asyncio
async def test_cotmreward_keeps_paying_after_one_deposit_fails(
    cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    ledger = _Ledger()
    real_apply = ledger.apply_operation

    async def flaky(**kwargs: Any) -> SimpleNamespace:
        if kwargs["user_id"] == 1:
            raise RuntimeError("database locked")
        return await real_apply(**kwargs)

    bot_mock.get_cog.return_value = SimpleNamespace(apply_operation=flaky)
    ctx_mock.guild = MagicMock(id=555)
    emote = const.COTM_VOTE_EMOJI
    channel = _channel([_entry(_person(1), {emote: _voters(3)}), _entry(_person(2), {emote: _voters(2, 2000)})])

    await cog.cotmreward.callback(cog, ctx_mock, channel)  # type: ignore[arg-type]

    assert set(ledger.paid) == {"cotm:1:2"}
    assert "Failed to deposit" in _payout_log(ctx_mock)


@pytest.mark.asyncio
async def test_cotmreward_rerun_pays_the_saved_places_after_votes_change(
    cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    ledger = _Ledger()
    real_apply = ledger.apply_operation

    async def second_place_fails_once(**kwargs: Any) -> SimpleNamespace:
        if kwargs["user_id"] == 2 and not any(c["user_id"] == 2 for c in ledger.calls):
            ledger.calls.append(kwargs)
            raise RuntimeError("database locked")
        return await real_apply(**kwargs)

    bot_mock.get_cog.return_value = SimpleNamespace(apply_operation=second_place_fails_once)
    ctx_mock.guild = MagicMock(id=555)
    emote = const.COTM_VOTE_EMOJI
    first, second, late = _person(1), _person(2), _person(3)
    before = _channel([_entry(first, {emote: _voters(5)}), _entry(second, {emote: _voters(3, 2000)})])
    # Between runs a new entry overtakes everyone and the second-place entry loses its votes
    after = _channel(
        [
            _entry(late, {emote: _voters(9, 5000)}),
            _entry(first, {emote: _voters(5)}),
            _entry(second, {emote: _voters(1, 2000)}),
        ]
    )

    await cog.cotmreward.callback(cog, ctx_mock, before, 8)  # type: ignore[arg-type]
    await cog.cotmreward.callback(cog, ctx_mock, after, 8)  # type: ignore[arg-type]

    assert ledger.paid == {"cotm:8:1": (1, const.COTM_REWARDS[0]), "cotm:8:2": (2, const.COTM_REWARDS[1])}
    after.history.assert_not_called()


@pytest.mark.asyncio
async def test_cotmreward_refuses_a_different_channel_for_a_decided_contest(
    cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    ledger = _Ledger()
    bot_mock.get_cog.return_value = ledger
    ctx_mock.guild = MagicMock(id=555)
    emote = const.COTM_VOTE_EMOJI
    await cog.cotmreward.callback(cog, ctx_mock, _channel([_entry(_person(1), {emote: _voters(2)})], 900), 9)  # type: ignore[arg-type]
    other = _channel([_entry(_person(4), {emote: _voters(2)})], 901)

    await cog.cotmreward.callback(cog, ctx_mock, other, 9)  # type: ignore[arg-type]

    assert set(ledger.paid) == {"cotm:9:1"}
    assert "already decided from <#900>" in ctx_mock.send.await_args.args[0]


@pytest.mark.asyncio
async def test_deleted_winner_is_forgotten_and_not_paid_on_rerun(
    cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    ledger = _Ledger()
    real_apply = ledger.apply_operation

    async def winner_fails(**kwargs: Any) -> SimpleNamespace:
        if kwargs["user_id"] == 1:
            raise RuntimeError("database locked")
        return await real_apply(**kwargs)

    bot_mock.get_cog.return_value = SimpleNamespace(apply_operation=winner_fails)
    ctx_mock.guild = MagicMock(id=555)
    emote = const.COTM_VOTE_EMOJI
    channel = _channel(
        [_entry(_person(1, "alice"), {emote: _voters(3)}), _entry(_person(2), {emote: _voters(2, 2000)})]
    )
    await cog.cotmreward.callback(cog, ctx_mock, channel, 6)  # type: ignore[arg-type]

    await cog.red_delete_data_for_user(requester="user", user_id=1)
    await cog.cotmreward.callback(cog, ctx_mock, channel, 6)  # type: ignore[arg-type]

    saved = (await cog.config.payouts())["6"]["placements"]
    assert saved[0] == {"user_id": None, "name": "Deleted user", "votes": 3, "amount": const.COTM_REWARDS[0]}
    assert "alice" not in str(await cog.config.payouts())
    assert set(ledger.paid) == {"cotm:6:2"}
    assert "#1 Deleted user**: not paid, their data was deleted" in _payout_log(ctx_mock)


@pytest.mark.asyncio
async def test_standings_are_cached_and_shared(cog: ContestCog, monkeypatch: pytest.MonkeyPatch) -> None:
    channel = _channel([_entry(_person(1), {const.COTM_VOTE_EMOJI: _voters(2)})])
    tally = AsyncMock(wraps=cog._get_contest_results)
    monkeypatch.setattr(cog, "_get_contest_results", tally)
    clock = [1000.0]
    monkeypatch.setattr("cotm.main.time.monotonic", lambda: clock[0])

    # Several presses at once share one tally.
    results = await asyncio.gather(*(cog.get_standings(channel) for _ in range(5)))
    assert tally.await_count == 1
    assert all(r == results[0] for r in results)

    clock[0] += const.STANDINGS_CACHE_SECONDS - 1
    await cog.get_standings(channel)
    assert tally.await_count == 1

    clock[0] += 2
    await cog.get_standings(channel)
    assert tally.await_count == 2


@pytest.mark.asyncio
async def test_standings_button_uses_the_shared_cache(cog: ContestCog) -> None:
    from cotm.cotm_views import ContestDashboardView, StandingsView

    channel = MagicMock(spec=discord.TextChannel)
    cog.get_standings = AsyncMock(return_value=([], datetime.now(UTC)))  # type: ignore[method-assign]
    view = ContestDashboardView(cog, 1, {"description": "", "terms": "", "prizes": "", "votes": ""})
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.client.get_channel.return_value = channel

    await view.standings_button(interaction)

    interaction.client.get_channel.assert_called_once_with(const.ENTRIES_CHANNEL_ID)
    cog.get_standings.assert_awaited_once_with(channel)
    assert isinstance(interaction.edit_original_response.call_args.kwargs["view"], StandingsView)
