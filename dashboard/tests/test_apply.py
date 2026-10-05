"""The staff application on the member site: who sees it, the checks on the answers, the message posted to the staff's
channel, and one application per member a week."""

from datetime import UTC, datetime
from math import ceil
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from dashboard.apply import (
    ACCENT,
    APPLICATIONS_CHANNEL,
    LONG_LIMIT,
    QUESTIONS,
    SECTIONS,
    SHORT_LIMIT,
    SITUATIONS,
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


def _card(view: discord.ui.LayoutView) -> dict[str, Any]:
    (card,) = view.to_components()  # one container per message
    return card


def _texts(view: discord.ui.LayoutView) -> list[str]:
    """Every text in the message, the header's included, in order."""
    found: list[str] = []

    def walk(component: dict[str, Any]) -> None:
        if component["type"] == 10:
            found.append(component["content"])
        for child in component.get("components", []):
            walk(child)

    walk(_card(view))
    return found


def _count(component: dict[str, Any]) -> int:
    """Components in a message, nested ones and accessories included, as Discord counts them toward its 40."""
    children = component.get("components", []) + ([component["accessory"]] if "accessory" in component else [])
    return 1 + sum(map(_count, children))


@pytest.mark.asyncio
async def test_the_message_is_one_card_with_the_applicant_then_each_section() -> None:
    (view,) = application_messages(_applicant(), _answers(why="first line\n\n  second line", other=""))
    card = _card(view)
    header, *rest = card["components"]
    sections = [component["content"] for component in rest if component["type"] == 10]
    assert card["type"] == 17 and card["accent_color"] == ACCENT
    assert header["type"] == 9 and header["accessory"]["media"]["url"] == "https://cdn.discordapp.com/avatar.png"
    assert [text["content"] for text in header["components"]] == [
        "## 📝 New staff application",
        f"<@{LEVEL_30}> · `sparkle` · `{LEVEL_30}`\n**Level** <@&{DIVINE}>\n"  # the highest level role
        "**Joined** <t:1704067200:D> · <t:1704067200:R>\n**Account created** <t:1704067200:D> · <t:1704067200:R>",
    ]
    assert [component["type"] for component in rest] == [14, 10] * len(SECTIONS)  # a divider before each section
    assert [text.split("\n")[0] for text in sections] == [f"### {s.emoji} {s.title}" for s in SECTIONS]
    assert sections[0].startswith(
        "### 🌸 About you\n-# What should we call you, and what are your pronouns?\nanswer to name\n\n"
        "-# How old are you?\n24\n\n"
    )
    assert "\n-# **1.** Two regulars roast" in sections[1] and "\n-# **7.** Another staff member" in sections[1]
    assert "you think is wrong.\n\n-# Your first pick\nanswer to pick1\n\n-# Your second pick\n" in sections[1]
    assert "-# Why do you want to do this?\nfirst line\nsecond line" in sections[3]
    assert sections[3].endswith("-# Anything else you want us to know?\n*No answer*")  # and no "part 1 of 1"


@pytest.mark.asyncio
async def test_markdown_in_an_answer_cannot_restyle_the_message() -> None:
    nasty = "# Heading\n```py\n> fake quote\n-# tiny\n**bold** [link](https://example.com)"
    (view,) = application_messages(_applicant(), _answers(why=nasty))
    expected = "\\# Heading\n\\`\\`\\`py\n\\> fake quote\n\\-# tiny\n\\*\\*bold\\*\\* \\[link](https://example.com)"
    assert expected in _texts(view)[-1]


@pytest.mark.asyncio
async def test_a_full_application_is_packed_into_few_messages_that_each_say_where_they_are() -> None:
    answers = {q.key: ("A fair answer with some detail. " * 50)[:LONG_LIMIT] if q.long else "x" * 60 for q in QUESTIONS}
    messages = application_messages(_applicant(), answers)
    texts = [_texts(view) for view in messages]
    # Whole answers only, so not every message can be full, but none is mostly empty
    assert len(messages) <= ceil(sum(len(text) for message in texts for text in message) / 4000) + 1
    assert all(sum(map(len, message)) > 2000 for message in texts[:-1])
    assert all(message[0] == f"-# <@{LEVEL_30}>'s staff application, continued" for message in texts[1:])
    assert [message[-1] for message in texts] == [f"-# part {n} of {len(messages)}" for n in range(1, len(texts) + 1)]
    sections = [text for message in texts for text in message if text.startswith("### ")]
    assert all("\n-# " in text for text in sections)  # no section heading is left without a question under it


@pytest.mark.asyncio
async def test_an_application_at_every_limit_still_fits_discord_and_loses_nothing() -> None:
    # Every character escaped and every other one a line break: the most an answer can grow in the message
    answers = {q.key: "*\n" * (LONG_LIMIT // 2) if q.long else "*" * SHORT_LIMIT for q in QUESTIONS}
    messages = application_messages(_applicant(), answers)
    texts = [_texts(view) for view in messages]
    assert all(sum(map(len, message)) <= 4000 for message in texts)
    assert all(_count(_card(view)) <= 40 for view in messages)
    lines = [line for message in texts for text in message for line in text.split("\n") if line.startswith("\\*")]
    assert len(lines) == sum(LONG_LIMIT // 2 if q.long else 1 for q in QUESTIONS)


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
    assert _texts(kwargs["view"])[0] == "## 📝 New staff application" and set(kwargs) == {"view", "allowed_mentions"}
    assert kwargs["allowed_mentions"].users is False and kwargs["allowed_mentions"].roles is False
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
