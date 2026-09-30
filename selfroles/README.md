# SelfRoles

Dropdown menus where members pick their own roles, replacing reaction roles. Each category is one message: its banner,
then a card with the heading ("Pick one." or "Pick up to 3."), the roles with their emoji and note, a dropdown and a
Clear button.

- Picking sets the member's roles in that category to exactly what they chose; Clear removes them all. The bot answers
  with a message only they can see.
- The dropdown enforces the pick limit. A menu holds at most 25 roles, Discord's limit for one dropdown.
- The menus keep working after a restart, and always use the category as it is now.
- Nobody is pinged: the role list shows role tags, but every post and edit goes out with mentions turned off.
- Members keep their roles when a role is taken off a menu or a category is deleted.
- A role can have a note of up to 100 characters, such as "Opens #little-chat". It shows in small text under the role in
  the list and under the option in the dropdown. A channel mention is a link in the list and `#name` in the dropdown.
- Posted menus keep up with the server: when a role on a menu is renamed or deleted, or gains or loses a moderator
  permission or its place below the bot, the menu is updated. Moving roles around otherwise leaves the menus alone.

## Which roles can go on a menu

A role can only be added when it is below the bot's top role, has no moderator permissions (anything that needs 2FA, such as
Kick, Ban, Manage Roles or Manage Messages, plus Mention Everyone, View Audit Log, Manage Nicknames, Manage Events and
the voice moderation permissions), and is below the top role of the person adding it (the server owner may add any).
The first two are checked again whenever someone picks, so a role that later gains such a permission stops being
handed out; the dashboard marks it "Not offered". A role can be on one menu only, since Clear on one menu would
otherwise take away a role picked on another.

## Commands

`[p]selfroles` needs Red's mod role or Manage Roles. Creating, posting and deleting also need Red's admin role or
Manage Server. Names with spaces go in quotes where another argument follows. Give a role by its name (in quotes) or
ID, not as an @mention: a mention in your command message pings everyone who has the role.

| Command | What it does |
| --- | --- |
| `[p]selfroles list` | Every category, its roles and where it is posted |
| `[p]selfroles create <max picks> <name>` | Create a category where members may pick up to that many roles |
| `[p]selfroles addrole <name> <role> [emoji]` | Add a role, with an optional emoji |
| `[p]selfroles note <name> <role> [note]` | Set a role's note, or clear it when none is given |
| `[p]selfroles emoji <name> <role> [emoji]` | Change a role's emoji, or clear it when none is given |
| `[p]selfroles removerole <name> <role>` | Take a role off |
| `[p]selfroles limit <max picks> <name>` | Change the pick limit |
| `[p]selfroles banner <name>` | Set the banner from the attached image (PNG, JPEG, GIF or WebP, up to 8 MB), or remove it when nothing is attached |
| `[p]selfroles post <name> [channel]` | Post the menu here or in the channel; the one posted before is deleted |
| `[p]selfroles delete <name>` | Delete the category and its posted menu |

Every change updates the posted menu right away. If Discord refuses the new menu (for example an emoji it doesn't
accept), the change is undone and the reason is shown. If the posted menu was deleted, the change is kept and the
category shows as not posted until it is posted again.

## Dashboard

Staff can add and remove roles on the staff site's Self roles page (`staff.unicornia.net/selfroles`); see
[dashboard/README.md](../dashboard/README.md). The emoji field there also takes `:name:` for one of the server's
emojis.

## Data

Guild Config: each category's name, pick limit, roles and emojis, and the channel and message it is posted in. Banners
are files in the cog's data folder (`banners/<guild id>/<category id>.<ext>`). No user data.
