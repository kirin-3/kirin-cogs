# Testing

How to write and run tests in this repo. Read this before adding or changing tests.

## Running

The environment is the `redenv/` virtualenv at the repo root (Windows paths shown; use `redenv/bin/` elsewhere).

```bash
redenv/Scripts/python.exe -m pytest -q --ignore=archived     # whole suite, about a minute
redenv/Scripts/python.exe -m pytest -q tickets/tests/        # one cog
redenv/Scripts/python.exe -m ruff format <paths> && redenv/Scripts/python.exe -m ruff check <paths>
redenv/Scripts/basedpyright.exe <paths>
```

New and changed test files must pass all three. `archived/` holds retired cogs; don't add tests there.

## Pick the right kind of test

| What you're testing | Use |
| --- | --- |
| Pure helpers, parsing, business logic | Plain `pytest` functions calling the code directly |
| Config schema migrations | `testutils.migration`: `DictConfig`, `historical_variants`, `assert_idempotent` (see `tickets/tests/test_tickets_migrations.py`) |
| Anything a Discord user does: commands, permission checks, listeners, buttons, selects, modals, slash commands, Config persistence | **`red_env`**: a real Red bot on SimCord's in-memory Discord (below) |
| External APIs (AI providers, Patreon, image hosts) | `unittest.mock.patch` + `AsyncMock` on the cog's client call. Never hit the network |

**dpytest is legacy.** About 15 older test files use it. Don't write new dpytest tests. Leave existing ones alone unless you are already changing that test file, then prefer moving the Discord-facing parts to `red_env`.

Avoid calling command callbacks directly (`await cog.mycommand.callback(cog, ctx)`) for new tests. That skips argument parsing and every permission decorator, which is where bugs hide. Use `red_env` and send the command as a user would.

## Layout and conventions

- Tests live in `<cog>/tests/` with an empty `__init__.py`. Files are named `test_*.py`.
- pytest-asyncio runs in **strict mode**: every async test needs `@pytest.mark.asyncio`, and async fixtures use `@pytest_asyncio.fixture`.
- Type-annotate tests. basedpyright runs in standard mode. Use `cast`, `isinstance` asserts or `assert x is not None` to narrow types, not `# type: ignore`.
- `testutils/tests/test_data_governance.py` checks every cog's `info.json` and deletion behavior. If you add a cog that stores user data, add it to `PERSISTENT_COGS` there.

## `red_env`: real Red on SimCord

`testutils/red.py` (registered by the root `conftest.py`) provides:

- `red_cogs`: the cog packages to load. Override it in your test module.
- `simcord_bot`: an actual `Red` instance with core cogs, global checks, the `!` prefix, and JSON Config in `tmp_path`. It loads your cogs through Red's own `--load-cogs` path, exactly like production.
- `red_env`: SimCord's `simcord_env` plus a clock fix. It logs the bot in and brings it to READY. **Always use `red_env`, never `simcord_env` directly** (see the clock gotcha below).

Each test gets a fresh bot and empty Config. Nothing carries over between tests.

`tickets/tests/test_simcord_tickets.py` is the reference example: prefix commands, a permission check, a button, a modal with a file upload, Config assertions and a slash command.

### Minimal test

```python
from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from mycog.mycog import MyCog


@pytest.fixture
def red_cogs() -> list[str]:
    return ["mycog"]  # several are fine: ["unicornia", "nitroaward"]


@pytest.mark.asyncio
async def test_admin_sets_log_channel(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("MyCog")
    assert isinstance(cog, MyCog)

    guild = red_env.create_guild()
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, f"!mycog logchannel {channel.id}")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)

    await admin.send(channel, f"!mycog logchannel {channel.id}")
    assert await cog.config.guild_from_id(guild.id).log_channel() == channel.id
    simcord.assert_no_errors(red_env)
```

### Building the world

- `red_env.create_guild()` makes a guild with a synthetic owner. The bot joins with a managed role that has every permission except administrator, so channel overwrites still apply to it.
- `guild.create_role(name, permissions=discord.Permissions(...))`, `guild.add_member(red_env.create_user(name), roles=[...])`
- `guild.create_text_channel(name, overwrites=..., category=...)`, `guild.create_category(name)`, plus voice, stage and forum helpers.
- `await red_env.settle()` after setup so the bot has processed the gateway events.
- `guild.channels[name]` and `guild.roles[name]` look up handles by name, which is useful for channels the bot creates.

Handles (`GuildHandle`, `ChannelHandle`, `MemberActor`) are SimCord's. To get discord.py objects the way the cog sees them, use the bot: `bot.get_channel(handle.id)`, `actor.member`.

### Acting as users

All of these run the bot until it goes idle before returning:

- `await member.send(channel, "!cmd args", attachments=[("a.png", b"...")])`: a message or prefix command.
- `await member.slash(channel, "name", option=value)`: a slash command. See the slash setup below.
- `await member.click(message, label="...")` or `custom_id="..."`: a button.
- `await member.select(message, ["value"], custom_id="...")`: a select menu.
- `await member.submit_modal(shown, {"custom_id": "text"})`, where `shown` is the result of the click or slash that opened the modal. File-upload fields take `(filename, bytes)`.
- `await member.react(message, "✅")`, `member.edit(...)`, `member.delete(...)`
- `await red_env.advance_time(seconds)`: moves SimCord's virtual clock and runs `tasks.loop`s, sleeps and view timeouts that fall due.

### Asserting

- Interactions return an `InteractionResult`: `.modal` (a dict or `None`), `.response` (the first reply: `.content`, `.embeds`, `.ephemeral`), `.followups`, `.deferred`.
- Channel messages: `channel_handle.history()` returns a list of `discord.Message`; also `channel_handle.last_message`.
- Helpers: `simcord.assert_sent(channel, contains=...)`, `simcord.assert_responded(result, content=..., ephemeral=True)`, `simcord.assert_error(env, SomeError)`.
- State: read the cog's Config directly (`await cog.config.guild_from_id(guild.id).key()`) and check Discord state through the bot (`channel.name`, `member.roles`).

### Errors: the rule that trips everyone up

SimCord captures every exception the bot raises in commands, listeners and callbacks. That includes Red's expected ones, such as `CheckFailure` from permission decorators and bad arguments. If a test never reads them, **the test fails at teardown** with those errors.

But reading `red_env.errors`, or calling `simcord.assert_error`, marks all errors as seen and turns that teardown check off for the rest of the test. So:

1. When you expect an error, **pop** it: `assert isinstance(red_env.errors.pop(), commands.CheckFailure)`.
2. End every test that expected an error with `simcord.assert_no_errors(red_env)`, so unexpected errors still fail it.

### Red specifics

- **Owner.** SimCord makes the bot user its own application owner, so no test user is a Red owner. Add one the way Red's `--owner` flag does: `bot.owner_ids.add(member.id)`.
- **Red admin and mod roles.** `is_admin_or_superior` and `@commands.admin()` check the roles registered with Red, not Discord's administrator permission. `admin_or_permissions(administrator=True)` accepts either. To give a role Red admin, have the owner run `!set roles addadminrole <role id>`.
- **Slash and hybrid commands.** Red only registers app commands the owner enables. Before `member.slash(...)`:

  ```python
  bot.owner_ids.add(admin.id)
  await admin.send(channel, "!slash enable <command>")
  await admin.send(channel, "!slash sync")
  ```

  SimCord's strict sync check then rejects any command that wasn't synced, just like Discord.
- **SimCord options.** `@pytest.mark.simcord(strict_sync=False, settle_timeout=10)` is still forwarded to SimCord through `red_env`.

### Gotchas

- **Only Discord is faked.** aiohttp calls to anything else are real. Mock external services in every test that could reach them. Loading `unicornia` downloads a font from GitHub on first load unless it's mocked.
- **Only Red's data folder is isolated.** Files a cog writes outside `cog_data_path` land in the source tree. `unicornia` puts `data/unicornia.db` and `data/fonts/` inside its package folder. Patch its paths into `tmp_path`, or don't load it.
- **Two clocks.** SimCord's virtual clock starts at 2026-01-01. `red_env` points `discord.utils.utcnow()` at it, because SimCord 2.2.1 doesn't, and discord.py would otherwise treat every interaction as expired. But `datetime.now()`, `datetime.utcnow()` and `time.time()` in cog code still read the real clock, and `advance_time()` doesn't move them. Tests of cooldowns, expiry or account age in those cogs need that call patched too.
- **Servers hang startup.** Cogs that open listening sockets (`dashboard`, `patron`'s webhook server) make SimCord time out with "bot did not settle". Mock the server start in those tests.
- **Unsupported Discord features fail loudly.** SimCord raises `RouteNotImplemented` or `UnsupportedField` rather than faking something wrong. Test that path with mocks instead of patching SimCord.
- **SimCord is pinned** (`simcord==2.2.1` in `requirements-dev.txt`). It releases often, so upgrade deliberately and re-run the suite.

### Debugging a failure

A failing `red_env` test gets a **simcord transcript** section: every HTTP call the bot made and every gateway event it received, in order. Read that first. Red's startup banner also appears in captured stdout; ignore it.

### Changing the harness

`testutils/red.py` works around several Red internals, each commented: process-wide Config caches and JSON driver state, the first-boot `--load-cogs` skip, extension unloading removing packages from `sys.modules`, the PyPI version check, and SimCord's clock. If a new cog needs something the fixture doesn't do, fix it there for everyone rather than in one cog's conftest, and run the whole suite afterwards.
