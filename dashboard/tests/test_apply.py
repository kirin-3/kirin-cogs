"""The staff application on the member site: who sees it, the checks on the answers, the message posted to the staff's
channel, and one application per member a week."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from dashboard.apply import APPLICATIONS_CHANNEL, EMBED_PAGE, LONG_LIMIT, QUESTIONS, application_embeds, read_answers
from dashboard.tests import test_member_site
from dashboard.tests.test_member_site import REGULAR, _get, _person, _post, _role

ms = test_member_site.ms  # the member site's fixture, reused

LEVEL_30 = 300000000000000030
PLATINUM, DIVINE = 714508825071190086, 721360680770469958


def _answers(**changes: str) -> dict[str, str]:
    return {q.key: f"answer to {q.key}" for q in QUESTIONS} | changes


def _applicant() -> Any:
    roles = [_role(PLATINUM, position=5), _role(DIVINE, position=9)]
    for role in roles:
        role.mention = f"<@&{role.id}>"
    member = _person(MagicMock(), LEVEL_30, roles)
    member.mention, member.name = f"<@{LEVEL_30}>", "sparkle"
    member.joined_at = member.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    member.display_avatar.url = "https://cdn.discordapp.com/avatar.png"
    return member


@pytest.fixture
def channel(ms: SimpleNamespace) -> MagicMock:
    ms.members[LEVEL_30] = _applicant()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = APPLICATIONS_CHANNEL
    channel.permissions_for.return_value = SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
    channel.send = AsyncMock()
    ms.bot.get_channel.side_effect = {APPLICATIONS_CHANNEL: channel}.get
    ms.bot.get_embed_colour = AsyncMock(return_value=discord.Colour(0x9401FE))
    return channel


def test_required_answers_must_be_there_and_line_breaks_count_once() -> None:
    _, missing = read_answers(_answers(age="  "))
    long_answer = "a\r\n" * (LONG_LIMIT // 2)  # LONG_LIMIT characters once the \r\n are \n
    answers, error = read_answers(_answers(why=long_answer, changes="", other=""))
    _, too_long = read_answers(_answers(why=long_answer + "b"))
    assert missing == "Answer “How old are you?” too."
    assert error == "" and "\r" not in answers["why"]
    assert too_long == "Your answer to “Why are you interested in being a staff member?” is too long."


def test_the_message_names_the_member_and_shows_every_question_with_its_answer() -> None:
    (embed,) = application_embeds(_applicant(), _answers(why="first line\n\nsecond line", other=""), discord.Colour(1))
    text = embed.description or ""
    assert embed.title == "Staff application" and embed.author.name == "member0 (sparkle)"
    assert f"<@{LEVEL_30}> (`sparkle`, `{LEVEL_30}`)" in text
    assert f"**Level role:** <@&{DIVINE}>" in text  # the highest one
    assert "### Scenario 2\n*One person is typing slurs against another person.*" in text
    assert "**How old are you?** answer to age" in text
    assert "**Why are you interested in being a staff member?**\n> first line\n> second line" in text
    assert "**Anything else you would like to add?**\n> *No answer*" in text


def test_a_long_application_is_split_into_parts_that_each_fit_an_embed() -> None:
    answers = _answers(**{q.key: "word " * (LONG_LIMIT // 5) for q in QUESTIONS if q.long})
    embeds = application_embeds(_applicant(), answers, discord.Colour(1))
    assert len(embeds) > 1
    assert all(len(e.description or "") <= EMBED_PAGE and e.author.name == "member0 (sparkle)" for e in embeds)
    assert [e.footer.text for e in embeds] == [f"Part {n} of {len(embeds)}" for n in range(1, len(embeds) + 1)]
    assert sum((e.description or "").count("> word") for e in embeds) == sum(q.long for q in QUESTIONS)


@pytest.mark.asyncio
async def test_only_level_30_members_see_the_tile_and_the_page(ms: SimpleNamespace, channel: MagicMock) -> None:
    _, home = await _get(ms, LEVEL_30, "/")
    _, other_home = await _get(ms, REGULAR, "/")
    status, page = await _get(ms, LEVEL_30, "/apply")
    refused, _ = await _get(ms, REGULAR, "/apply")
    response = await _post(ms, REGULAR, "/apply", _answers())
    assert 'href="/apply"' in home and 'href="/apply"' not in other_home
    assert status == 200 and page.count("<textarea") == sum(q.long for q in QUESTIONS)
    assert refused == 403 and response.status == 403 and not channel.send.called


@pytest.mark.asyncio
async def test_an_application_is_posted_once_and_the_member_must_wait_a_week(
    ms: SimpleNamespace, channel: MagicMock
) -> None:
    response = await _post(ms, LEVEL_30, "/apply", _answers())
    _, thanks = await _get(ms, LEVEL_30, "/apply?sent=1")
    _, later = await _get(ms, LEVEL_30, "/apply")
    again = await _post(ms, LEVEL_30, "/apply", _answers(about="me <b>again</b>"))
    assert response.status == 303 and response.headers["Location"] == "/apply?sent=1"
    assert "was sent to the staff" in thanks and "You can send another in 7 days." in later
    assert channel.send.await_count == 1
    kwargs = channel.send.await_args.kwargs
    assert kwargs["embed"].title == "Staff application" and kwargs["allowed_mentions"].users is False
    page = await again.text()
    assert again.status == 400 and "You can send another in 7 days." in page
    assert "me &lt;b&gt;again&lt;/b&gt;</textarea>" in page  # the answers come back, escaped


@pytest.mark.asyncio
async def test_a_refused_application_keeps_the_answers_and_does_not_count(
    ms: SimpleNamespace, channel: MagicMock
) -> None:
    missing = await _post(ms, LEVEL_30, "/apply", _answers(why=""))
    channel.permissions_for.return_value.embed_links = False
    unavailable = await _post(ms, LEVEL_30, "/apply", _answers())
    channel.permissions_for.return_value.embed_links = True
    sent = await _post(ms, LEVEL_30, "/apply", _answers())
    assert missing.status == 400 and 'value="answer to age"' in await missing.text()
    assert unavailable.status == 400 and "be sent right now" in await unavailable.text()
    assert sent.status == 303 and channel.send.await_count == 1
