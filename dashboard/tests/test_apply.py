"""The staff application on the member site: who sees it, the checks on the answers, the message posted to the staff's
channel, and one application per member a week."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from dashboard.apply import (
    APPLICATIONS_CHANNEL,
    LONG_LIMIT,
    QUESTIONS,
    SECTIONS,
    SHORT_LIMIT,
    SITUATIONS,
    TONES,
    application_messages,
    read_answers,
)
from dashboard.tests import test_member_site
from dashboard.tests.test_member_site import REGULAR, _get, _person, _post, _role

ms = test_member_site.ms  # the member site's fixture, reused

LEVEL_30 = 300000000000000030
PLATINUM, DIVINE = 714508825071190086, 721360680770469958


def _answers(**changes: str) -> dict[str, str]:
    return {q.key: "24" if q.digits else f"answer to {q.key}" for q in QUESTIONS} | changes


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
    return channel


def test_required_answers_must_be_there_and_line_breaks_count_once() -> None:
    _, missing = read_answers(_answers(around="  "))
    long_answer = "a\r\n" * (LONG_LIMIT // 2)  # LONG_LIMIT characters once the \r\n are \n
    answers, error = read_answers(_answers(why=long_answer, boundaries="", other=""))
    _, too_long = read_answers(_answers(why=long_answer + "b"))
    assert missing == "Answer “What's your time zone, and when are you usually around?” too."
    assert error == "" and "\r" not in answers["why"]
    assert too_long == "Your answer to “Why do you want to do this?” is too long."


@pytest.mark.parametrize("age", ["7", "123", "2a", "twenty", " 2 4", "²⁴", "٢٤", "-1"])
def test_the_age_must_be_a_two_digit_number(age: str) -> None:
    assert read_answers(_answers(age=age))[1] == "Answer “How old are you?” with a 2-digit number."


def test_a_two_digit_age_is_accepted() -> None:
    assert read_answers(_answers(age="24")) == (_answers(age="24"), "")


def test_the_message_is_a_header_then_a_card_per_section_with_every_answer() -> None:
    (embeds,) = application_messages(_applicant(), _answers(why="first line\n\n  second line", other=""))
    header, *sections = embeds
    fields = {field.name: field.value for field in header.fields}
    assert (
        header.title == "📝 New staff application" and header.thumbnail.url == "https://cdn.discordapp.com/avatar.png"
    )
    assert fields["Member"] == f"<@{LEVEL_30}>\n`sparkle`" and fields["User ID"] == f"`{LEVEL_30}`"
    assert fields["Level"] == f"<@&{DIVINE}>"  # the highest one
    assert fields["Joined the server"] == "<t:1704067200:D>\n<t:1704067200:R>"
    assert [e.title for e in sections] == [
        "🌸 About you",
        "💭 How you'd handle things",
        "🫶 Being honest",
        "✨ Last bit",
    ]
    assert [e.colour.value for e in sections if e.colour] == [TONES[section.tone] for section in SECTIONS]
    handling, last = sections[1].description or "", sections[3].description or ""
    assert handling.startswith("*There's no right answer.")
    assert "**1.** Two regulars roast" in handling and "**7.** Another staff member" in handling  # for the picks
    assert "**Your first pick**\n> answer to pick1\n\n**Your second pick**" in handling
    assert "**Why do you want to do this?**\n> first line\n> second line" in last
    assert last.endswith("**Anything else you want us to know?**\n*No answer*")
    assert all(not e.footer.text and not e.author.name for e in embeds)  # one message needs no part numbers


def test_markdown_in_an_answer_cannot_restyle_the_message() -> None:
    nasty = "# Heading\n```py\n> fake quote\n-# tiny\n**bold** [link](https://example.com)"
    (embeds,) = application_messages(_applicant(), _answers(why=nasty))
    expected = (
        "> \\# Heading\n> \\`\\`\\`py\n> \\> fake quote\n> \\-# tiny\n> \\*\\*bold\\*\\* \\[link](https://example.com)"
    )
    assert expected in (embeds[-1].description or "")


def test_a_full_application_is_packed_into_few_messages_that_each_say_where_they_are() -> None:
    answers = {q.key: ("A fair answer with some detail. " * 50)[:LONG_LIMIT] if q.long else "x" * 60 for q in QUESTIONS}
    messages = application_messages(_applicant(), answers)
    cards = [embed for message in messages for embed in message][1:]
    assert len(messages) <= 4
    assert all(message[0].title for message in messages)  # every message starts with the section's name
    assert all(not embed.title for message in messages for embed in message[1:] if "(continued)" in (embed.title or ""))
    assert all("**" in (card.description or "") for card in cards)  # no card holds only a section's intro


def test_an_application_at_every_limit_still_fits_discord_and_loses_nothing() -> None:
    # Every character escaped and every other one a line break: the most an answer can grow in the message
    answers = {q.key: "*\n" * (LONG_LIMIT // 2) if q.long else "*" * SHORT_LIMIT for q in QUESTIONS}
    messages = application_messages(_applicant(), answers)
    embeds = [embed for message in messages for embed in message]
    assert len(messages) > 1
    assert all(len(message) <= 10 and sum(map(len, message)) <= 6000 for message in messages)
    assert all(len(embed.description or "") <= 4096 and len(embed.title or "") <= 256 for embed in embeds)
    parts = [f"Staff application · part {n} of {len(messages)}" for n in range(1, len(messages) + 1)]
    assert [message[-1].footer.text for message in messages] == parts
    assert all(message[0].author.name == "member0 (sparkle)" for message in messages[1:])
    quoted = [line for embed in embeds for line in (embed.description or "").splitlines() if line.startswith("> ")]
    assert len(quoted) == sum(LONG_LIMIT // 2 if q.long else 1 for q in QUESTIONS)


@pytest.mark.asyncio
async def test_only_level_30_members_see_the_tile_and_the_page(ms: SimpleNamespace, channel: MagicMock) -> None:
    _, home = await _get(ms, LEVEL_30, "/")
    _, other_home = await _get(ms, REGULAR, "/")
    status, page = await _get(ms, LEVEL_30, "/apply")
    refused, _ = await _get(ms, REGULAR, "/apply")
    response = await _post(ms, REGULAR, "/apply", _answers())
    assert 'href="/apply"' in home and 'href="/apply"' not in other_home
    assert status == 200 and page.count("<textarea") == sum(q.long for q in QUESTIONS)
    situations = page.split('<ol class="situations">')[1].split("</ol>")[0]
    assert situations.count("<li>") == len(SITUATIONS) and "<li>Two regulars roast" in situations
    assert "senior staff or Kirin rather than" in page and page.count("data-count") == page.count("<textarea")
    assert 'name="age" inputmode="numeric" pattern="[0-9]{2}" maxlength="2"' in page  # a box, not a drop-down
    assert "<select" not in page
    assert refused == 403 and response.status == 403 and not channel.send.called


@pytest.mark.asyncio
async def test_an_application_is_posted_once_and_the_member_must_wait_a_week(
    ms: SimpleNamespace, channel: MagicMock
) -> None:
    response = await _post(ms, LEVEL_30, "/apply", _answers())
    _, thanks = await _get(ms, LEVEL_30, "/apply?sent=1")
    _, later = await _get(ms, LEVEL_30, "/apply")
    again = await _post(ms, LEVEL_30, "/apply", _answers(why="me <b>again</b>"))
    assert response.status == 303 and response.headers["Location"] == "/apply?sent=1"
    assert "Your application is with the staff now." in thanks and "You can send another in 7 days." in later
    assert channel.send.await_count == 1
    kwargs = channel.send.await_args.kwargs
    assert kwargs["embeds"][0].title == "📝 New staff application" and kwargs["allowed_mentions"].users is False
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
    assert missing.status == 400 and 'value="answer to name"' in await missing.text()
    assert unavailable.status == 400 and "be sent right now" in await unavailable.text()
    assert sent.status == 303 and channel.send.await_count == 1
