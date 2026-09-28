"""The settings dashboard: a member's roleplay settings with buttons for the on/off
settings and dropdowns for the user lists. It's ephemeral and only the member who
opened it can use it."""

import contextlib
from typing import TYPE_CHECKING, Any, cast

import discord
from redbot.core import commands

from . import const
from .user_settings import USER_SETTINGS

if TYPE_CHECKING:
    from .settings import Settings

TOGGLES = [key for key, values in USER_SETTINGS.items() if isinstance(values["default"], bool)]
LISTS = [key for key, values in USER_SETTINGS.items() if isinstance(values["default"], list)]


class InteractionReplies:
    """Stands in for the ``ctx`` the user list helpers answer through, so the dashboard
    can reuse them. Questions (messages with buttons, like asking someone to be an owner)
    go to the channel; everything else goes only to the member."""

    def __init__(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction
        self.author = interaction.user
        self.guild = interaction.guild

    async def send(self, content: str | None = None, *, view: discord.ui.View | None = None, **_: Any):
        if view is None:
            return await self.interaction.followup.send(content or "​", ephemeral=True, wait=True)
        return await self.interaction.followup.send(content or "​", view=view, wait=True)


class SettingsDashboard(discord.ui.View):
    def __init__(self, settings: "Settings", member: discord.abc.User, viewer_id: int) -> None:
        super().__init__(timeout=const.LONG_DELETE_TIME)
        self.settings = settings
        self.member = member
        self.viewer_id = viewer_id
        # the last interaction that showed this dashboard, to disable it on timeout
        self.interaction: discord.Interaction | None = None

    @classmethod
    async def open(
        cls, settings: "Settings", member: discord.abc.User, viewer_id: int
    ) -> tuple[discord.Embed, "SettingsDashboard"]:
        view = cls(settings, member, viewer_id)
        await view.populate()
        return await settings.settings_embed(member), view

    async def populate(self) -> None:
        """Rebuild the controls from the member's current settings."""
        self.clear_items()
        data = await self.settings.config.user(self.member).all()
        for key in TOGGLES:
            self.add_item(ToggleButton(key, bool(data.get(key))))
        self.add_item(OpenActionsButton())
        remove_options: list[discord.SelectOption] = []
        for key in LISTS:
            self.add_item(AddUserSelect(key))
            user_ids = await self.settings.users_manager.list_users(self.member, key)
            names = await self.settings.users_manager.display_names(user_ids)
            values = USER_SETTINGS[key]
            remove_options += [
                discord.SelectOption(
                    label=name[:100],
                    value=f"{key}:{user_id}",
                    description=f"from {values['label']}",
                    emoji=values["emoji"],
                )
                for user_id, name in zip(user_ids, names, strict=True)
            ]
        if remove_options:
            # ponytail: a select holds 25 options, so longer lists need the remove command for the rest
            self.add_item(RemoveUserSelect(remove_options[:25]))

    async def refresh(self, interaction: discord.Interaction) -> None:
        """Show the member's settings as they are now. The interaction must already be answered."""
        await self.populate()
        self.interaction = interaction
        await interaction.edit_original_response(embed=await self.settings.settings_embed(self.member), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.viewer_id:
            return True
        await interaction.response.send_message("These aren't your settings.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        if self.interaction is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.interaction.edit_original_response(view=None)


class ToggleButton(discord.ui.Button[SettingsDashboard]):
    def __init__(self, key: str, value: bool) -> None:
        values = USER_SETTINGS[key]
        super().__init__(
            label=values["label"],
            emoji=values["emoji"],
            style=discord.ButtonStyle.success if value else discord.ButtonStyle.secondary,
            custom_id=f"roleplay:toggle:{key}",
            row=0,
        )
        self.key = key
        self.value = value

    async def callback(self, interaction: discord.Interaction) -> None:
        dashboard = cast(SettingsDashboard, self.view)
        await interaction.response.defer()
        value = not self.value
        await dashboard.settings.config.user(dashboard.member).get_attr(self.key).set(value)
        await dashboard.settings.parent.setting_changed(dashboard.member.id, self.key, value)
        await dashboard.refresh(interaction)


class OpenActionsButton(discord.ui.Button[SettingsDashboard]):
    def __init__(self) -> None:
        super().__init__(
            label="Always Allowed Actions",
            emoji="✨",
            style=discord.ButtonStyle.primary,
            custom_id="roleplay:actions",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        dashboard = cast(SettingsDashboard, self.view)
        picker = ActionsPicker(dashboard)
        await picker.populate()
        await interaction.response.send_message(ActionsPicker.CONTENT, view=picker, ephemeral=True)


class ActionsPicker(discord.ui.View):
    """Pick the actions a member consents to from anyone. Only actions that ask for
    consent are listed, split over as many dropdowns as it takes (25 options each)."""

    CONTENT = (
        "Pick the actions you consent to from anyone, except your blocked members. You'll still be asked for the rest."
    )

    def __init__(self, dashboard: SettingsDashboard) -> None:
        super().__init__(timeout=const.LONG_DELETE_TIME)
        self.dashboard = dashboard

    async def populate(self) -> None:
        self.clear_items()
        chosen = set(await self.dashboard.settings.consented_actions(self.dashboard.member))
        names = sorted(a.name for a in self.dashboard.settings.parent.action_manager.actions if a.consent.required)
        for row, start in enumerate(range(0, len(names), 25)):
            self.add_item(ActionsSelect(names[start : start + 25], chosen, row))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.dashboard.interaction_check(interaction)


class ActionsSelect(discord.ui.Select[ActionsPicker]):
    def __init__(self, names: list[str], chosen: set[str], row: int) -> None:
        super().__init__(
            placeholder=f"✨ {names[0]} to {names[-1]}",
            options=[discord.SelectOption(label=name, default=name in chosen) for name in names],
            min_values=0,
            max_values=len(names),
            custom_id=f"roleplay:actions:{row}",
            row=row,
        )
        self.names = set(names)

    async def callback(self, interaction: discord.Interaction) -> None:
        picker = cast(ActionsPicker, self.view)
        dashboard = picker.dashboard
        await interaction.response.defer()
        # This dropdown decides for its own actions; the other dropdowns' picks are kept
        current = set(await dashboard.settings.consented_actions(dashboard.member))
        names = sorted((current - self.names) | set(self.values))
        await dashboard.settings.config.user(dashboard.member).consented_actions.set(names)
        await picker.populate()
        await interaction.edit_original_response(view=picker)
        if dashboard.interaction is not None:
            with contextlib.suppress(discord.HTTPException):
                await dashboard.refresh(dashboard.interaction)


class AddUserSelect(discord.ui.UserSelect[SettingsDashboard]):
    def __init__(self, key: str) -> None:
        values = USER_SETTINGS[key]
        placeholder = "Set your owner" if key == "owners" else f"Add to {values['label']}"
        super().__init__(
            placeholder=f"{values['emoji']} {placeholder}", custom_id=f"roleplay:add:{key}", row=1 + LISTS.index(key)
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        dashboard = cast(SettingsDashboard, self.view)
        await interaction.response.defer()
        # The same checks and messages as [p]roleplay settings <list> add, including asking an owner first
        await dashboard.settings.users_manager.add_user_to_group(
            cast(commands.Context, InteractionReplies(interaction)),
            dashboard.member,
            self.values[0].id,
            self.key,
            exclusion_groups=("blocked",),
        )
        await dashboard.refresh(interaction)


class RemoveUserSelect(discord.ui.Select[SettingsDashboard]):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Remove someone from a list", options=options, custom_id="roleplay:remove", row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        dashboard = cast(SettingsDashboard, self.view)
        await interaction.response.defer()
        key, user_id = self.values[0].split(":")
        await dashboard.settings.users_manager.remove_user(
            cast(commands.Context, InteractionReplies(interaction)), dashboard.member, int(user_id), key
        )
        await dashboard.refresh(interaction)


class OpenDashboardView(discord.ui.View):
    """The button a prefix command shows, since only an interaction can answer ephemerally."""

    def __init__(self, settings: "Settings", member: discord.abc.User, viewer_id: int) -> None:
        super().__init__(timeout=const.SHORT_DELETE_TIME)
        self.settings = settings
        self.member = member
        self.viewer_id = viewer_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.viewer_id:
            return True
        await interaction.response.send_message("These aren't your settings.", ephemeral=True)
        return False

    @discord.ui.button(label="Show Settings", style=discord.ButtonStyle.primary)
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed, dashboard = await SettingsDashboard.open(self.settings, self.member, self.viewer_id)
        dashboard.interaction = interaction
        await interaction.response.send_message(embed=embed, view=dashboard, ephemeral=True)
