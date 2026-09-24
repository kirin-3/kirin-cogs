"""Regression tests: builder edits, stored pictures, members leaving, and age validation."""

from profile.models import AGE_RULE, QUESTIONS, parse_age
from profile.profile import Profile
from profile.views import PictureUploadModal, ProfileBuilderView, UploadedPicture
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from .test_profile import _make_interaction, _make_member, _make_profile_config_mock


def _question(field_id: str) -> dict[str, Any]:
    return next(q for q in QUESTIONS if q["id"] == field_id)


def _not_found() -> discord.NotFound:
    return discord.NotFound(MagicMock(status=404, reason="Not Found"), "Unknown Message")


def _forbidden() -> discord.Forbidden:
    return discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Missing Access")


class _FakeModal:
    """Stands in for ProfileModal: already submitted (or dismissed) when awaited."""

    value: Any = None
    interaction: Any = None

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def wait(self) -> None:
        return None


def _modal_interaction() -> MagicMock:
    modal_interaction = MagicMock(spec=discord.Interaction)
    modal_interaction.edit_original_response = AsyncMock()
    modal_interaction.followup.send = AsyncMock()
    return modal_interaction


async def _fill(view: ProfileBuilderView, field_id: str, value: str | None, modal_interaction: Any) -> MagicMock:
    button_interaction = _make_interaction(cast(MagicMock, view.user))
    button_interaction.message = MagicMock(spec=discord.Message)
    button_interaction.message.edit = AsyncMock()
    fake = type("Submitted", (_FakeModal,), {"value": value, "interaction": modal_interaction})
    with patch("profile.views.ProfileModal", fake):
        await view._make_callback(_question(field_id))(button_interaction)
    return button_interaction


# ---------------------------------------------------------------------------
# Builder refresh on the ephemeral message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_field_updates_builder_through_the_modal_interaction() -> None:
    view = ProfileBuilderView(_make_member(), {})
    modal_interaction = _modal_interaction()

    button_interaction = await _fill(view, "name", "Alice", modal_interaction)

    assert view.data.get("name") == "Alice"
    modal_interaction.edit_original_response.assert_awaited_once_with(view=view)
    # Message.edit on an ephemeral message 404s, which used to post a new builder for every field
    button_interaction.message.edit.assert_not_awaited()
    modal_interaction.followup.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_dismissed_builder_continues_in_a_new_message() -> None:
    view = ProfileBuilderView(_make_member(), {})
    modal_interaction = _modal_interaction()
    modal_interaction.edit_original_response.side_effect = _not_found()

    await _fill(view, "name", "Alice", modal_interaction)

    modal_interaction.followup.send.assert_awaited_once()
    assert modal_interaction.followup.send.call_args.kwargs["view"] is view


@pytest.mark.asyncio
async def test_dismissed_modal_changes_nothing() -> None:
    view = ProfileBuilderView(_make_member(), {"name": "Alice"})

    await _fill(view, "name", None, None)

    assert view.data == {"name": "Alice"}


# ---------------------------------------------------------------------------
# Age validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("18", 18),
        (" 30 ", 30),
        ("100", 100),
        ("0", None),
        ("-5", None),
        ("17", None),
        ("101", None),
        ("abc", None),
        ("", None),
        ("2_5", None),
        ("²", None),
    ],
)
def test_parse_age(text: str, expected: int | None) -> None:
    assert parse_age(text) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["0", "-5", "17"])
async def test_builder_rejects_invalid_age(text: str) -> None:
    view = ProfileBuilderView(_make_member(), {"age": 25})
    modal_interaction = _modal_interaction()

    await _fill(view, "age", text, modal_interaction)

    assert view.data.get("age") == 25
    modal_interaction.followup.send.assert_awaited_once_with(AGE_RULE, ephemeral=True)
    modal_interaction.edit_original_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_builder_stores_valid_age_as_int() -> None:
    view = ProfileBuilderView(_make_member(), {})

    await _fill(view, "age", "21", _modal_interaction())

    assert view.data.get("age") == 21


@pytest.mark.asyncio
async def test_submit_rejects_invalid_stored_age() -> None:
    data = {"name": "A", "age": 5, "location": "EU", "gender": "x", "sexuality": "y"}
    view = ProfileBuilderView(_make_member(), data)  # type: ignore[arg-type]
    interaction = _make_interaction(cast(MagicMock, view.user))

    await view.submit_callback(interaction)

    assert view.submitted is False
    assert AGE_RULE in interaction.response.send_message.call_args.args[0]


# ---------------------------------------------------------------------------
# Picture upload is downloaded and re-attached
# ---------------------------------------------------------------------------


def _attachment(content_type: str | None = "image/png", size: int = 1000, data: bytes = b"png-bytes") -> MagicMock:
    attachment = MagicMock(spec=discord.Attachment)
    attachment.content_type = content_type
    attachment.size = size
    attachment.filename = "IMG_0001.PNG"
    attachment.url = "https://cdn.discordapp.com/ephemeral-attachments/1/2/IMG_0001.PNG?ex=abc"
    attachment.read = AsyncMock(return_value=data)
    return attachment


async def _submit_upload(attachment: MagicMock) -> PictureUploadModal:
    modal = PictureUploadModal()
    modal.image._values = [attachment]
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.defer = AsyncMock()
    await modal.on_submit(interaction)
    return modal


@pytest.mark.asyncio
async def test_upload_is_downloaded_not_saved_as_link() -> None:
    modal = await _submit_upload(_attachment(content_type="image/jpeg"))

    assert modal.value == UploadedPicture(data=b"png-bytes", filename="profile_picture.jpg")
    assert modal.error is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attachment",
    [_attachment(content_type="application/pdf"), _attachment(content_type=None), _attachment(size=9 * 1024 * 1024)],
)
async def test_upload_rejects_non_images_and_large_files(attachment: MagicMock) -> None:
    modal = await _submit_upload(attachment)

    assert modal.value is None
    assert modal.error
    attachment.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_builder_keeps_uploaded_picture_for_the_post() -> None:
    view = ProfileBuilderView(_make_member(), {})
    modal_interaction = _modal_interaction()
    picture = UploadedPicture(b"img", "profile_picture.png")

    class Uploaded(_FakeModal):
        value = picture
        error = None
        interaction = modal_interaction

    with patch("profile.views.PictureUploadModal", Uploaded):
        await view._make_callback(_question("picture_url"))(_make_interaction(cast(MagicMock, view.user)))

    assert view.picture is picture
    assert view.data.get("picture_url") == "attachment://profile_picture.png"
    modal_interaction.edit_original_response.assert_awaited_once()


# ---------------------------------------------------------------------------
# Posting the picture with the profile
# ---------------------------------------------------------------------------


def _cog_with_channel(message_id: int | None = None) -> tuple[Profile, MagicMock, MagicMock]:
    config = _make_profile_config_mock()
    config.member.return_value.message_id = AsyncMock(return_value=message_id)
    config.member.return_value.message_id.set = AsyncMock()
    bot = MagicMock()
    with patch("profile.profile.Config.get_conf", return_value=config):
        cog = Profile(bot)
    cog.config = config
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock(return_value=MagicMock(id=789))
    cog.get_profile_channel = AsyncMock(return_value=channel)  # type: ignore[method-assign]
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]
    return cog, config, channel


@pytest.mark.asyncio
async def test_new_picture_is_attached_to_the_post() -> None:
    cog, _, channel = _cog_with_channel()
    data: dict[str, Any] = {"name": "Alice", "picture_url": "attachment://profile_picture.png"}

    await cog._update_profile_embed(_make_member(), data, picture=UploadedPicture(b"img", "profile_picture.png"))  # type: ignore[arg-type]

    kwargs = channel.send.call_args.kwargs
    assert [f.filename for f in kwargs["files"]] == ["profile_picture.png"]
    assert kwargs["files"][0].fp.read() == b"img"
    assert kwargs["embed"].image.url == "attachment://profile_picture.png"


@pytest.mark.asyncio
async def test_editing_other_fields_carries_the_picture_over() -> None:
    cog, _, channel = _cog_with_channel(message_id=456)
    existing = MagicMock(spec=discord.Message)
    existing.attachments = [_attachment(data=b"old-img")]
    existing.attachments[0].filename = "profile_picture.png"
    channel.fetch_message = AsyncMock(return_value=existing)
    post = MagicMock(spec=discord.Message)
    post.edit = AsyncMock()
    channel.get_partial_message.return_value = post
    data: dict[str, Any] = {"name": "Alice B.", "picture_url": "attachment://profile_picture.png"}

    await cog._update_profile_embed(_make_member(), data)  # type: ignore[arg-type]

    kwargs = post.edit.call_args.kwargs
    assert [f.filename for f in kwargs["attachments"]] == ["profile_picture.png"]
    assert kwargs["attachments"][0].fp.read() == b"old-img"
    assert kwargs["embed"].image.url == "attachment://profile_picture.png"
    assert data["picture_url"] == "attachment://profile_picture.png"


@pytest.mark.asyncio
async def test_picture_is_dropped_when_the_post_is_gone() -> None:
    cog, _, channel = _cog_with_channel(message_id=456)
    channel.fetch_message = AsyncMock(side_effect=_not_found())
    post = MagicMock(spec=discord.Message)
    post.edit = AsyncMock(side_effect=_not_found())
    channel.get_partial_message.return_value = post
    data: dict[str, Any] = {"name": "Alice", "picture_url": "attachment://profile_picture.png"}

    await cog._update_profile_embed(_make_member(), data)  # type: ignore[arg-type]

    assert data["picture_url"] is None
    kwargs = channel.send.call_args.kwargs
    assert kwargs["files"] == []
    assert kwargs["embed"].image.url is None


@pytest.mark.asyncio
async def test_legacy_picture_link_is_still_shown() -> None:
    cog, _, channel = _cog_with_channel()

    await cog._update_profile_embed(_make_member(), {"picture_url": "https://example.com/old.png"})  # type: ignore[arg-type]

    assert channel.send.call_args.kwargs["embed"].image.url == "https://example.com/old.png"


# ---------------------------------------------------------------------------
# Members leaving
# ---------------------------------------------------------------------------


def _member_record(config: MagicMock, message_id: int | None) -> MagicMock:
    record = MagicMock()
    record.message_id = AsyncMock(return_value=message_id)
    record.message_id.clear = AsyncMock()
    record.profile_data.clear = AsyncMock()
    record.last_delete.clear = AsyncMock()
    record.clear = AsyncMock()
    config.member_from_ids = MagicMock(return_value=record)
    return record


@pytest.mark.asyncio
async def test_leaving_member_profile_post_and_answers_are_removed() -> None:
    cog, config, channel = _cog_with_channel()
    record = _member_record(config, 456)
    post = MagicMock(spec=discord.Message)
    post.delete = AsyncMock()
    channel.get_partial_message.return_value = post
    member = _make_member()
    member.guild = MagicMock(spec=discord.Guild, id=1)

    await cog.on_member_remove(member)

    config.member_from_ids.assert_called_once_with(1, member.id)
    channel.get_partial_message.assert_called_once_with(456)
    post.delete.assert_awaited_once()
    record.profile_data.clear.assert_awaited_once()
    record.message_id.clear.assert_awaited_once()
    # The 24h re-creation cooldown survives leaving and rejoining
    record.last_delete.clear.assert_not_awaited()
    record.clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_leaving_member_record_kept_when_post_cannot_be_deleted() -> None:
    cog, config, channel = _cog_with_channel()
    record = _member_record(config, 456)
    channel.get_partial_message.return_value.delete = AsyncMock(side_effect=_forbidden())

    assert await cog._remove_profile(MagicMock(spec=discord.Guild, id=1), 123) is False
    record.profile_data.clear.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_removes_profiles_of_people_who_left() -> None:
    cog, config, _ = _cog_with_channel()
    guild = MagicMock(spec=discord.Guild, id=1, chunked=True)
    guild.get_member.side_effect = lambda user_id: MagicMock() if user_id == 2 else None
    config.all_members = AsyncMock(
        return_value={
            1: {"profile_data": {"name": "Gone"}, "message_id": 10},
            2: {"profile_data": {"name": "Here"}, "message_id": 20},
            3: {"profile_data": {}, "message_id": None, "last_delete": 1.0},
        }
    )
    cog._remove_profile = AsyncMock(return_value=True)  # type: ignore[method-assign]
    ctx = MagicMock()
    ctx.guild = guild
    ctx.send = AsyncMock()

    await cog.profileset_cleanup.callback(cog, ctx)  # type: ignore[arg-type]

    cog._remove_profile.assert_awaited_once_with(guild, 1)
    assert "Removed 1 profile(s)" in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_cleanup_waits_for_the_member_list() -> None:
    cog, _, _ = _cog_with_channel()
    ctx = MagicMock()
    ctx.guild = MagicMock(spec=discord.Guild, chunked=False)
    ctx.send = AsyncMock()
    cog._remove_profile = AsyncMock()  # type: ignore[method-assign]

    await cog.profileset_cleanup.callback(cog, ctx)  # type: ignore[arg-type]

    cog._remove_profile.assert_not_awaited()
    assert "isn't fully loaded" in ctx.send.call_args.args[0]
