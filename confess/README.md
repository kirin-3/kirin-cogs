# Confess

Confess is a Discord bot cog that allows users to submit anonymous confessions in a designated confession channel. The cog provides a sticky message with a confession button that stays at the bottom of the channel, making it easy for users to share their secrets or admissions anonymously.

## Features

- **Anonymous Confessions**: Users can submit confessions that appear under an "Anonymous Confession" tag without revealing their identity
- **Sticky Message**: A persistent message with a confession button that remains visible in the confession channel
- **Modal Interface**: Clean, user-friendly modal form for submitting confessions
- **Moderator Logging**: All confessions are logged to bot owners for moderation purposes
- **Message Management**: Automatically manages the sticky message, recreating it if deleted

## Setup

1. Set up a dedicated text channel for confessions (currently hardcoded to channel ID `898576602441605120`)
2. Ensure the bot has permissions to read/send messages, manage messages, and delete messages in this channel
3. Load the cog with `[p]load confess` or add it to your auto-load cogs
4. The sticky message will automatically appear in the confession channel

## Usage

Users can submit confessions by clicking the "Confess" button (🙈) in the sticky message at the bottom of the confession channel. This opens a modal where they can type their confession (minimum 5 characters, maximum 2000 characters).

Once submitted, the confession appears in the channel as an anonymous post, and the user receives a confirmation message: "Your confession has been sent, you are forgiven now."

## Configuration

The confession channel ID is currently hardcoded in the cog as `898576602441605120`. To change this:

1. Contact your bot administrator to modify the `CONFESSION_CHANNEL_ID` constant in the cog's code
2. Update the channel ID to your desired confession channel's ID

## Commands

This cog does not provide any user-facing commands. All functionality is accessed through the sticky message interface in the configured confession channel.

## Moderation

- All confessions are logged to bot owners with user information for oversight
- The confession channel requires careful moderation as it's designed for anonymous posts
- Owners can monitor content through the automated logging system

## Data Storage

This cog stores minimal data:
- The message ID of the sticky message (for tracking purposes)
- No user data or confession content is permanently stored

## Technical Details

- The sticky message automatically reposts itself if deleted
- Includes cooldown mechanisms to prevent message spam
- Uses Discord's modal system for secure confession entry
- Includes proper mention escaping to prevent abuse