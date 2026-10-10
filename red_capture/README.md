# red_capture

A throwaway Red cog that records the exact JSON the bot sends to Discord, so the Rust port's
reference files (task 1.6) come from real payloads instead of screenshots.

## Use

1. Put the `red_capture` folder somewhere Red can load from, e.g. on the test bot:
   `[p]addpath <folder that contains red_capture>` then `[p]load red_capture`.
2. As a bot owner, in the test server: `[p]capture start`.
3. Run the commands listed in `capture-script.md`, pressing the buttons on menus where asked.
4. `[p]capture stop`, then `[p]capture file` (the bot DMs you `capture.jsonl`).
5. `[p]unload red_capture` when done.

Only your own commands, your interactions and the bot's replies to them are recorded. No tokens or
headers are written. The file does contain names, IDs and text from the server, so use a test
server and skip anything that shows secrets (`[p]set api`).

## Check

```bash
cd python-bot
PYTHONPATH=../tools:. redenv/Scripts/python.exe -m pytest ../tools/red_capture/tests -q --rootdir=.
```
