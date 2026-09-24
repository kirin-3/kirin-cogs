"""Only staff can set a verification status, and the configured modal title/fields reach the verification modal."""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from tickets.common.constants import MAX_MODAL_FIELDS, MODAL_SCHEMA
from tickets.common.utils import is_ticket_staff
from tickets.common.views import CloseReasonModal, CloseView, VerificationModal, VerificationStatusView
from tickets.tests.test_record_resilience import (
    USER_ID,
    _active,
    _Config,
    _creation_setup,
    _guild,
    _member,
    _state,
    _text_channel,
)

SUPPORT_ROLE_ID = 7
STAFF_ID = 99


def _staff(guild: MagicMock) -> MagicMock:
    staff = _member(guild)
    staff.id = STAFF_ID
    staff.name = "staff"
    staff.roles = [MagicMock(id=SUPPORT_ROLE_ID)]
    return staff


def _field(label: str, **extra: Any) -> dict:
    return {**MODAL_SCHEMA, "label": label, **extra}


def _close_view(state: dict, channel: MagicMock) -> CloseView:
    view = object.__new__(CloseView)
    view.bot = MagicMock()
    view.config = cast(Any, _Config(state))
    view.owner_id = USER_ID
    view.channel = channel
    return view


def _interaction(guild: MagicMock, user: MagicMock, channel: MagicMock) -> MagicMock:
    interaction = MagicMock()
    interaction.guild = guild
    interaction.user = user
    interaction.channel = channel
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    return interaction


def _ticket_setup() -> tuple[dict, MagicMock, MagicMock, MagicMock, MagicMock]:
    channel = _text_channel(100)
    guild = _guild({100: channel})
    guild.owner_id = 1
    channel.guild = guild
    owner = _member(guild)
    staff = _staff(guild)
    guild.get_member.side_effect = {USER_ID: owner, STAFF_ID: staff}.get
    state = _state(
        support_roles=[[SUPPORT_ROLE_ID, False]],
        user_can_close=True,
        opened={str(USER_ID): {"100": _active("2024-01-01T00:00:00+00:00")}},
    )
    return state, guild, channel, owner, staff


# --- staff check ---


@pytest.mark.asyncio
async def test_is_ticket_staff() -> None:
    state, guild, _channel, owner, staff = _ticket_setup()
    with patch("tickets.common.utils.is_admin_or_superior", new=AsyncMock(return_value=False)):
        assert await is_ticket_staff(MagicMock(), guild, staff, state) is True
        assert await is_ticket_staff(MagicMock(), guild, owner, state) is False
        guild.owner_id = USER_ID
        assert await is_ticket_staff(MagicMock(), guild, owner, state) is True
    guild.owner_id = 1
    with patch("tickets.common.utils.is_admin_or_superior", new=AsyncMock(return_value=True)):
        assert await is_ticket_staff(MagicMock(), guild, owner, state) is True


# --- close button ---


@pytest.mark.asyncio
async def test_owner_close_button_skips_verification_choice() -> None:
    state, guild, channel, owner, _staff_member = _ticket_setup()
    interaction = _interaction(guild, owner, channel)

    with patch("tickets.common.utils.is_admin_or_superior", new=AsyncMock(return_value=False)):
        await CloseView.closeticket(_close_view(state, channel), interaction, MagicMock())  # pyright: ignore[reportCallIssue]

    interaction.response.send_message.assert_not_awaited()
    interaction.response.send_modal.assert_awaited_once()
    modal = interaction.response.send_modal.await_args.args[0]
    assert isinstance(modal, CloseReasonModal)
    assert modal.status is None


@pytest.mark.asyncio
async def test_staff_close_button_shows_verification_choice() -> None:
    state, guild, channel, _owner, staff = _ticket_setup()
    interaction = _interaction(guild, staff, channel)

    with patch("tickets.common.utils.is_admin_or_superior", new=AsyncMock(return_value=False)):
        await CloseView.closeticket(_close_view(state, channel), interaction, MagicMock())  # pyright: ignore[reportCallIssue]

    interaction.response.send_modal.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    assert isinstance(interaction.response.send_message.await_args.kwargs["view"], VerificationStatusView)


# --- verification buttons ---


@pytest.mark.asyncio
async def test_verification_buttons_reject_non_staff() -> None:
    state, guild, channel, owner, staff = _ticket_setup()
    view = VerificationStatusView(MagicMock(), cast(Any, _Config(state)), USER_ID, channel, state)

    with patch("tickets.common.utils.is_admin_or_superior", new=AsyncMock(return_value=False)):
        owner_interaction = _interaction(guild, owner, channel)
        assert await view.interaction_check(owner_interaction) is False
        owner_interaction.response.send_message.assert_awaited_once()

        staff_interaction = _interaction(guild, staff, channel)
        assert await view.interaction_check(staff_interaction) is True
        staff_interaction.response.send_message.assert_not_awaited()


# --- verification modal ---


def test_verification_modal_defaults() -> None:
    guild = _guild({})
    modal = VerificationModal(MagicMock(), guild, MagicMock(), _member(guild), _state())

    assert modal.title == "Verification"
    assert len(modal.children) == 1
    assert modal.questions == []


def test_verification_modal_uses_title_and_fields() -> None:
    guild = _guild({})
    conf = _state(
        modal_title="Age Check",
        modal={
            "username": _field("Your username", placeholder="kirin", max_length=32),
            "notes": _field("Anything else?", style="long", required=False),
        },
    )
    modal = VerificationModal(MagicMock(), guild, MagicMock(), _member(guild), conf)

    assert modal.title == "Age Check"
    assert len(modal.children) == 3
    assert [label for label, _ in modal.questions] == ["Your username", "Anything else?"]
    username, notes = (text_input for _, text_input in modal.questions)
    assert username.placeholder == "kirin"
    assert username.max_length == 32
    assert username.required is True
    assert notes.style == discord.TextStyle.paragraph
    assert notes.required is False


def test_verification_modal_caps_legacy_fields() -> None:
    guild = _guild({})
    conf = _state(modal={f"q{i}": _field(f"Question {i}") for i in range(5)})
    modal = VerificationModal(MagicMock(), guild, MagicMock(), _member(guild), conf)

    assert len(modal.questions) == MAX_MODAL_FIELDS
    assert len(modal.children) == MAX_MODAL_FIELDS + 1


@pytest.mark.asyncio
async def test_verification_modal_submits_answers() -> None:
    guild = _guild({})
    conf = _state(modal={"a": _field("Filled"), "b": _field("Skipped", required=False)})
    member = _member(guild)
    cog = MagicMock()
    cog.create_ticket_for_user = AsyncMock(return_value="Ticket has been created!")
    bot = MagicMock()
    bot.get_cog.return_value = cog
    modal = VerificationModal(bot, guild, cast(Any, _Config(conf)), member, conf)
    modal.questions[0][1]._value = "yes"
    modal.questions[1][1]._value = ""
    interaction = MagicMock()
    interaction.data = {}
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    with patch("tickets.common.functions.Functions", new=MagicMock):
        await modal.on_submit(interaction)

    cog.create_ticket_for_user.assert_awaited_once_with(member, answers={"Filled": "yes"})


@pytest.mark.asyncio
async def test_verification_modal_keeps_answers_to_fields_with_the_same_label() -> None:
    guild = _guild({})
    conf = _state(modal={"a": _field("Age"), "b": _field("Age"), "c": _field("Age")})
    member = _member(guild)
    cog = MagicMock()
    cog.create_ticket_for_user = AsyncMock(return_value="Ticket has been created!")
    bot = MagicMock()
    bot.get_cog.return_value = cog
    modal = VerificationModal(bot, guild, cast(Any, _Config(conf)), member, conf)
    for (_, text_input), value in zip(modal.questions, ["20", "21", "22"], strict=True):
        text_input._value = value
    interaction = MagicMock()
    interaction.data = {}
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    with patch("tickets.common.functions.Functions", new=MagicMock):
        await modal.on_submit(interaction)

    cog.create_ticket_for_user.assert_awaited_once_with(member, answers={"Age": "20", "Age (2)": "21", "Age (3)": "22"})


# --- ticket creation ---


@pytest.mark.asyncio
async def test_create_ticket_posts_and_stores_answers() -> None:
    cog, state, member, ticket_channel = _creation_setup(_text_channel(30))

    with patch("tickets.common.functions.update_active_overview", new=AsyncMock(return_value=None)):
        await cog.create_ticket_for_user(member, answers={"Your username": "kirin"})

    answer_embeds = [
        call.kwargs["embed"]
        for call in ticket_channel.send.await_args_list
        if getattr(call.kwargs.get("embed"), "title", None) == "Submission Info"
    ]
    assert len(answer_embeds) == 1
    assert [(f.name, f.value) for f in answer_embeds[0].fields] == [("Your username", "kirin")]
    record = state["opened"][str(USER_ID)]["500"]
    assert record["answers"] == {"Your username": "kirin"}
    assert record["has_response"] is True
