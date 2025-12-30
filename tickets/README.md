# Tickets (Simplified) A Fork of https://github.com/vertyco/vrt-cogs

A robust, single-panel support ticket system for Red Discord Bot.

## Features
- **Single Panel**: Easy to set up and manage.
- **Button Interaction**: Users open tickets with a simple button click.
- **Modals**: Collect information from users before the ticket opens.
- **Working Hours**: Restrict ticket opening times or warn users.
- **Automation**: Auto-close inactive tickets.

## Commands

### User Commands
- `[p]add <user>`: Add a user to your ticket.
- `[p]renameticket <new_name>`: Rename your ticket channel.
- `[p]close [reason]`: Close your ticket.

### Admin Commands (`[p]tickets`)
Base support ticket settings. Alias: `[p]tset`

#### Setup
1. `[p]tickets category <category>`: Set the category where new tickets will be created.
2. `[p]tickets channel <channel>`: Set the channel where the panel message will be located.
3. `[p]tickets panelmessage <message>`: Set the existing message that the "Open Ticket" button will be attached to.
4. (Optional) `[p]tickets embed`: Create a stylized message (embed) to use as the panel message.

#### Customization
- `[p]tickets buttontext <text>`: Set the text on the open button.
- `[p]tickets buttoncolor <color>`: Set the button color (red, blue, green, grey).
- `[p]tickets buttonemoji <emoji>`: Set an emoji for the button.
- `[p]tickets ticketname <format>`: Set the naming format for new ticket channels (supports variables like `{num}`, `{user}`).
- `[p]tickets addmessage`: Add an embed to be sent inside the ticket when it opens.
- `[p]tickets viewmessages`: View/delete these internal ticket messages.
- `[p]tickets logchannel <channel>`: Set a channel for logging opened/closed tickets.

#### Modals (Input Forms)
- `[p]tickets modaltitle <title>`: Set the title of the input form.
- `[p]tickets addmodal <field_name>`: Add or edit a field in the modal (e.g., "Username", "Issue").
- `[p]tickets viewmodal`: View and delete configured modal fields.

#### Access Control
- `[p]tickets supportrole <role>`: Add/remove roles that can manage tickets.
- `[p]tickets blacklist <user_or_role>`: Prevent specific users/roles from opening tickets.
- `[p]tickets openrole <role>`: If set, only users with these roles can open tickets.
- `[p]tickets maxtickets <amount>`: Max concurrent open tickets per user.

#### Automation & Toggles
- `[p]tickets dm`: Toggle whether the bot DMs users when their ticket is closed.
- `[p]tickets selfrename`: Allow users to rename their own tickets.
- `[p]tickets selfclose`: Allow users to close their own tickets.
- `[p]tickets selfmanage`: Allow users to add others to their tickets.
- `[p]tickets noresponse <hours>`: Auto-close tickets if the user doesn't respond for X hours.
- `[p]tickets suspend`: Temporarily suspend ticket creation with a message.
- `[p]tickets cleanup`: Prune tickets from the database that no longer exist.


#### Info
- `[p]tickets view`: View current configuration.
- `[p]tickets overview`: Set a channel for a live-updating list of active tickets.
- `[p]tickets overviewmention`: Toggle channel mentions in the overview.
- `[p]tickets setuphelp`: View a step-by-step setup guide.

### Mod Commands
- `[p]openfor <user>`: Open a ticket on behalf of another user.
