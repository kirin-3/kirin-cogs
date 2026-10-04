# VoiceNoteLog

> Fork of [voicenotelog](https://github.com/japandotorg/Seina-Cogs/tree/main/voicenotelog) by japandotorg
> ([Seina-Cogs](https://github.com/japandotorg/Seina-Cogs)), MIT (see [LICENSE](LICENSE)).

Transcribes members' voice notes and posts the text to a log channel, with a button that jumps to the voice note.

The original stopped working on the aarch64 VPS: its SpeechRecognition library needs a `flac` binary and only ships x86
builds. This fork converts the audio with ffmpeg and sends it to Google Cloud Speech-to-Text (v1) over HTTPS with
aiohttp, so nothing blocks the bot while it works. Notes longer than a minute are transcribed in full.

- Only real voice notes are transcribed (Discord's voice message flag), up to 25 MB.
- If the log channel is missing or the bot can't send embeds there, a warning is logged and logging stays enabled.
- Transcripts longer than about 3,800 characters are cut short.

## Requirements

- `ffmpeg` on the host (`/usr/bin/ffmpeg` on the VPS).
- A Google Cloud API key restricted to the Speech-to-Text API, set with `[p]set api google_speech api_key,<key>`. The
  first 60 minutes of audio a month are free, then it costs $0.024 a minute. Without a key every voice note is skipped
  with a warning in the log.
- Logging is **off by default**; run `[p]voicenotelog toggle true` to start transcribing.

## Commands

All commands need `Manage Server` or Red's mod role. The alias `[p]vnl` also works.

| Command | What it does |
| --- | --- |
| `[p]voicenotelog channel [channel]` | Set the log channel (text channel or thread), or clear it |
| `[p]voicenotelog toggle <true/false>` | Turn logging on or off |
| `[p]voicenotelog settings` (aliases `showsettings`, `show`) | Show the channel and whether logging is on |

## Migrating from Seina-Cogs

The cog reads the Config the original saved (`VoiceNoteLog`, same identifier). Unload and uninstall Seina-Cogs'
`voicenotelog`, then install and load this one.
