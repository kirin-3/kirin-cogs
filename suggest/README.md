# Suggest

A comprehensive suggestion system that allows server members to submit, vote on, and track suggestions through an interactive interface.

## What It Does

This cog provides a complete suggestion management system with:
- Interactive button for submitting suggestions via modal
- Automatic posting to a dedicated suggestions channel
- Upvote/downvote reaction system with custom emojis
- Sticky message that stays at the bottom of the channel for easy access
- Owner commands to approve or reject suggestions with reasons
- Automatic DM notifications to users when their suggestion is resolved
- Vote statistics displayed on resolved suggestions

## Commands

All commands require **Bot Owner** permissions.

### `approve`
Approves a suggestion and updates the suggestion message with approval status.

**Usage:**
```
[ p ] approve <suggestion_id> [reason]
```

**Example:**
```
[ p ] approve 135 Great idea! We'll implement this soon.
```

### `reject`
Rejects a suggestion and updates the suggestion message with rejection status.

**Usage:**
```
[ p ] reject <suggestion_id> [reason]
```

**Example:**
```
[ p ] reject 136 This doesn't align with our server goals.
```

## How Members Use It

### Submitting a Suggestion
1. Click the **"Make a Suggestion"** button (💡) on the sticky message in the suggestions channel
2. A modal dialog opens where you can type your suggestion (5-2000 characters)
3. Submit the form to post your suggestion anonymously with your display name
4. Your suggestion appears as an embed with a unique ID number

### Voting on Suggestions
- React with ✅ (upvote) or ❌ (downvote) to vote on suggestions
- Voting is mutually exclusive: you can only have one vote per suggestion
- Switching your vote automatically removes the previous reaction

### Tracking Your Suggestion
- Suggestions start with "Pending Review" status
- When reviewed, the embed updates to show "Approved" or "Rejected"
- You receive a DM notification with the decision and reason
- Final vote counts are displayed on resolved suggestions

## How Administrators Use It

### Reviewing Suggestions
1. Monitor the suggestions channel for new submissions
2. Review the content and community votes
3. Use `[ p ] approve` or `[ p ] reject` with the suggestion ID
4. Optionally provide a reason explaining the decision

### Sticky Message
- The cog automatically maintains a sticky message at the bottom of the channel
- If the sticky message is deleted, it will be automatically reposted
- The sticky message contains the suggestion submission button

## Configuration

The cog uses the following hardcoded settings:
- **Suggestions Channel ID:** 998190508847403060
- **Upvote Emoji ID:** 729330852747542568
- **Downvote Emoji ID:** 729330876114141215

## Notes

- Suggestion IDs are automatically incremented and unique
- The sticky message has a 3-second cooldown before reposting to prevent spam
- All suggestion data is stored including author ID, content, message ID, status, and review reason
- Bot owner only commands ensure only authorized users can resolve suggestions
