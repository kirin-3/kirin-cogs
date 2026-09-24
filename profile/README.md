# Profile Cog

The Profile cog allows server members to create and manage personal profiles in a designated channel. Users interact with a persistent sticky message that provides buttons to create, edit, or delete their profile. The cog uses an interactive modal-based system to collect profile information and displays it as an embed.

## Features

- **Interactive Profile Builder**: Users fill out profile information through a series of modal dialogs
- **Sticky Message System**: Keeps the profile creation buttons always accessible at the bottom of the channel
- **Profile Embeds**: Creates beautifully formatted embeds with user profile information
- **Automatic Updates**: Users can edit their profiles at any time
- **24-Hour Cooldown**: Prevents abuse by requiring a 24-hour wait after deleting a profile before creating a new one
- **Persistent Messages**: Tracks profile messages and updates them when users edit their profiles
- **Customizable Fields**: Collects various profile information including name, age, location, gender, sexuality, and more

## Profile Fields

The following fields can be included in a user's profile:

### Required Fields (marked with *)
- **Name**: What name the user goes by
- **Age**: User's age (a whole number from 18 to 100)
- **Location**: Where the user is from (country or continent)
- **Gender**: User's gender identity
- **Sexuality**: User's sexuality

### Optional Fields
- **Role**: Preferred role (Sub/Dom/Switch)
- **Likes**: Hobbies and general interests
- **Dislikes**: Things the user dislikes
- **Kinks**: User's kinks
- **Limits**: User's limits
- **About Me**: Additional information about the user
- **Picture**: Profile picture (PNG, JPEG, GIF or WebP, up to 8 MB). The upload is attached to the profile post itself,
  because the link of a builder upload is temporary

## Setup Guide

### 1. Load the Cog
```
[p]load profile
```

### 2. Configure the Profile Channel
Set the channel where profiles will be displayed:
```
[p]profileset channel #profile-channel
```

### 3. (Optional) Force Repost Sticky Message
If the sticky message gets deleted or needs to be refreshed:
```
[p]profileset fix
```

## Commands

### Administrator Commands

**`[p]profileset channel <channel>`**
- Sets the channel where user profiles will be posted
- The sticky message will automatically be created in this channel
- **Permission Required**: Admin or Manage Guild

**`[p]profileset fix`**
- Forces the sticky message to be reposted in the profile channel
- Useful if the sticky message was accidentally deleted
- **Permission Required**: Admin or Manage Guild

**`[p]profileset cleanup`**
- Deletes the profile posts and stored answers of people who are no longer in the server
- New departures are handled automatically; run this once for profiles left behind before that
- **Permission Required**: Admin or Manage Guild

## User Commands

Users interact with the profile system through buttons on the sticky message in the profile channel. No text commands are needed.

### Creating or Editing a Profile

1. Navigate to the profile channel
2. Click the **"Create/Edit Profile"** button on the sticky message
3. Fill out each field by clicking the corresponding button
   - Required fields are marked with *
   - Completed fields show a ✅ checkmark
   - Buttons turn green when filled, purple for required empty fields, and grey for optional empty fields
4. Click **"Submit Profile"** when finished
5. Your profile embed will be posted in the channel with your mention

### Deleting a Profile

1. Navigate to the profile channel
2. Click the **"Delete Profile"** button on the sticky message
3. Confirm the deletion by clicking **"Yes, Delete"**
4. **Note**: You must wait 24 hours after deleting your profile before creating a new one

## How It Works

### Sticky Message System
The cog maintains a "sticky" message at the bottom of the profile channel. This message contains the buttons for creating and deleting profiles. The system automatically:
- Reposts the sticky message if it gets deleted
- Keeps the sticky message at the bottom of the channel
- Applies a cooldown (default 3 seconds) to prevent spam when reposting

### Profile Management
- When a user creates or updates their profile, an embed is posted in the profile channel
- The embed includes the user's mention, profile information, and avatar
- Users can update their profile information at any time by using the Create/Edit button
- The cog tracks each user's profile message ID to enable editing instead of creating duplicates
- When a member leaves or is removed, their profile post and stored answers are deleted. The 24-hour cooldown after a
  self-deletion still applies if they rejoin

### Cooldown System
To prevent abuse, users who delete their profiles must wait 24 hours before creating a new one. This cooldown does not apply to editing existing profiles, only to creating new profiles after deletion.

## Configuration

The cog uses the following default settings:

| Setting | Default | Description |
|---------|---------|-------------|
| Channel ID | 686091267012296714 | Default profile channel (change with `[p]profileset channel`) |
| Cooldown | 3 seconds | Time between sticky message reposts |
| Sticky Message | Auto-generated | Created automatically in the profile channel |

## Notes

- **Bot Permissions**: The bot needs permission to send messages, attach files, manage messages, and read message history in the profile channel
- **Profile Privacy**: Profiles are public and visible to all members in the designated channel
- **Data Storage**: Profile data is stored in the bot's configuration and linked to user IDs
- **Profile Message Deletion**: If a user's profile message is deleted (by mods or the user), they can recreate it by editing their profile
- **Owner Exception**: Bot owners bypass the 24-hour deletion cooldown

## Troubleshooting

**Sticky message not appearing?**
- Ensure the profile channel is set correctly with `[p]profileset channel`
- Use `[p]profileset fix` to force a repost
- Check that the bot has proper permissions in the channel

**Can't create a profile?**
- Make sure you're clicking the button in the correct channel
- Check if you recently deleted a profile (24-hour cooldown applies)
- Ensure all required fields are filled before submitting

**Profile not updating?**
- Use the Create/Edit button to update your existing profile
- The cog will edit your existing message rather than creating a new one

**Button not responding?**
- The sticky message buttons are persistent and do not expire; if a click does nothing, check the bot's console log or use `[p]profileset fix` to repost the sticky message.
- The profile builder view itself times out after 10 minutes of inactivity — reopen it with the "Create/Edit Profile" button.

Profile settings are guild-scoped and answers are stored per guild/member. Legacy global/user records are adopted lazily without deleting the source, so rollback remains possible. Uploaded pictures use the canonical `picture_url` field: `attachment://<file>` for a
picture attached to the profile post. Older profiles that saved the upload's link keep showing that link, which may
have stopped working; re-uploading the picture fixes it.
