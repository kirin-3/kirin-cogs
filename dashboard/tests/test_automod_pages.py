"""Automod pages on the staff site: owner-only changes, read-only staff views, and the scriptless editor."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

import automod.automod as automod_module
from automod.automod import AutoMod
from automod.tests.helpers import document, rule, ruleset, word_list
from dashboard.dashboard import OWNER_ONLY
from dashboard.tests.test_dashboard import CSRF, _log_in, site  # noqa: F401  (site is a fixture)
from testutils import DictGroup

STAFF_ROLE, GOLD_ROLE, GONE_ROLE = 696020813299580940, 715522934084468786, 424242


@dataclass(order=True)
class _Role:
    position: int
    id: int
    name: str

    def is_default(self) -> bool:
        return self.position == 0


class _Config(DictGroup):
    def register_global(self, **defaults: Any) -> None:
        self._store.update(defaults)


RULES = document(
    ruleset(
        "invite",
        [
            rule(
                "invite",
                [{"type": "invite"}],
                [{"type": "delete"}, {"type": "mute", "minutes": 1440, "reason": "Invite"}],
                [{"type": "ignore_roles", "roles": [GOLD_ROLE, GONE_ROLE]}],
            ),
            rule("words", [{"type": "words", "list": 900}], [{"type": "delete"}]),
        ],
    ),
    lists=[word_list("slurs", ["badword"], 900)],
)


@pytest_asyncio.fixture
async def am(site: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:  # noqa: F811
    monkeypatch.setattr(automod_module.Config, "get_conf", lambda *a, **k: _Config({}))
    monkeypatch.setattr(AutoMod, "sweep", MagicMock())
    cog = AutoMod(MagicMock())
    await cog.cog_load()
    await cog.save(RULES)
    site.bot.get_cog.side_effect = lambda name: cog if name == "AutoMod" else None
    site.bot.is_owner = AsyncMock(return_value=True)
    site.guild.roles = [_Role(0, 1, "@everyone"), _Role(5, STAFF_ROLE, "Staff"), _Role(3, GOLD_ROLE, "Gold")]
    site.guild.channels = [SimpleNamespace(id=10, name="general", position=0)]
    site.headers = _log_in(site)
    site.automod = cog
    return site


def _ids(doc: dict) -> dict[str, int]:
    invite = doc["rulesets"][0]
    return {"ruleset": invite["id"], "rule": invite["rules"][0]["id"], "words_rule": invite["rules"][1]["id"]}


async def _post(page: SimpleNamespace, path: str, data: list | dict | None = None, *, csrf: bool = True):
    data = list(data.items()) if isinstance(data, dict) else list(data or [])
    if csrf:
        data.append(("csrf", CSRF))
    return await page.client.post(path, data=data, headers=page.headers, allow_redirects=False)


def _rule_form(name: str = "invite", pattern: str | None = None, action: str = "save") -> list:
    form = [("name", name), ("triggers-0-type", "invite"), ("effects-0-type", "delete"), ("action", action)]
    if pattern is not None:
        form += [("triggers-1-type", "regex"), ("triggers-1-pattern", pattern)]
    return form


def test_every_automod_post_route_is_owner_only(site: SimpleNamespace) -> None:  # noqa: F811
    posts = {
        route.resource.canonical
        for route in site.client.app.router.routes()
        if route.method == "POST" and route.resource is not None and route.resource.canonical.startswith("/automod")
    }
    assert posts == OWNER_ONLY


@pytest.mark.asyncio
async def test_non_owner_staff_get_403_and_nothing_changes(am: SimpleNamespace) -> None:
    am.bot.is_owner = AsyncMock(return_value=False)
    before = await am.automod.document()
    ids = _ids(before)
    for path, data in [
        ("/automod/dryrun", {"dry_run": "off"}),
        (f"/automod/rules/{ids['rule']}", _rule_form("renamed")),
        (f"/automod/rulesets/{ids['ruleset']}/delete", None),
        ("/automod/lists/900/delete", None),
    ]:
        response = await _post(am, path, data)
        assert response.status == 403, path
    assert await am.automod.document() == before
    assert am.automod.dry_run is True


@pytest.mark.asyncio
async def test_owner_needs_the_csrf_token_too(am: SimpleNamespace) -> None:
    response = await _post(am, "/automod/dryrun", {"dry_run": "off"}, csrf=False)
    assert response.status == 403
    assert am.automod.dry_run is True

    response = await _post(am, "/automod/dryrun", {"dry_run": "off"})
    assert (response.status, response.headers["Location"]) == (302, "/automod")
    assert am.automod.dry_run is False


@pytest.mark.asyncio
async def test_staff_see_rules_without_edit_controls(am: SimpleNamespace) -> None:
    am.bot.is_owner = AsyncMock(return_value=False)
    ids = _ids(await am.automod.document())
    overview = await (await am.client.get("/automod", headers=am.headers)).text()
    assert "Dry-run is on." in overview
    assert "invite" in overview and "slurs" in overview
    assert "<form" not in overview.split("</header>")[1]

    page = await (await am.client.get(f"/automod/rulesets/{ids['ruleset']}", headers=am.headers)).text()
    assert "Member has none of @Gold, Deleted role 424242" in page
    assert "Mute for 1440 min (0 = until unmuted): Invite" in page
    assert "Message contains a word from list “slurs”" in page
    assert "Edit rule" not in page and 'method="post" action="/automod' not in page

    listing = await (await am.client.get("/automod/lists/900", headers=am.headers)).text()
    assert "<li>badword</li>" in listing and "<textarea" not in listing


@pytest.mark.asyncio
async def test_pages_explain_when_automod_is_unloaded(am: SimpleNamespace) -> None:
    am.bot.get_cog.side_effect = None
    am.bot.get_cog.return_value = None
    for path in ("/automod", "/automod/log", "/automod/rulesets/1", "/automod/lists/900"):
        text = await (await am.client.get(path, headers=am.headers)).text()
        assert "Automod is not loaded" in text, path


@pytest.mark.asyncio
async def test_adding_a_row_renders_a_draft_and_stores_nothing(am: SimpleNamespace) -> None:
    before = await am.automod.document()
    ids = _ids(before)
    form = [*_rule_form("edited", pattern="changed"), ("new-triggers", "words")]
    form = [(k, "add-triggers" if k == "action" else v) for k, v in form]
    response = await _post(am, f"/automod/rules/{ids['rule']}", form)
    text = await response.text()

    assert response.status == 200
    assert 'value="edited"' in text and 'value="changed"' in text
    assert 'name="triggers-2-type" value="words"' in text  # the new row, unsaved
    assert await am.automod.document() == before


@pytest.mark.asyncio
async def test_removing_a_row_renders_the_draft_without_it(am: SimpleNamespace) -> None:
    ids = _ids(await am.automod.document())
    response = await _post(am, f"/automod/rules/{ids['rule']}", _rule_form(pattern="x", action="remove-triggers-1"))
    text = await response.text()
    assert 'name="triggers-1-type"' not in text.split('id="rule-new"')[0].split(f'id="rule-{ids["rule"]}"')[1]


@pytest.mark.asyncio
async def test_invalid_regex_keeps_the_submitted_values(am: SimpleNamespace) -> None:
    before = await am.automod.document()
    ids = _ids(before)
    response = await _post(am, f"/automod/rules/{ids['rule']}", _rule_form("renamed", pattern="(unclosed"))
    text = await response.text()
    assert response.status == 400
    assert "trigger 2 (Regex match), pattern: invalid regex" in text
    assert 'value="renamed"' in text and 'value="(unclosed"' in text
    assert await am.automod.document() == before


@pytest.mark.asyncio
async def test_valid_save_redirects_and_applies(am: SimpleNamespace) -> None:
    ids = _ids(await am.automod.document())
    response = await _post(am, f"/automod/rules/{ids['rule']}", _rule_form("links", pattern="free nitro"))
    assert (response.status, response.headers["Location"]) == (
        302,
        f"/automod/rulesets/{ids['ruleset']}#rule-{ids['rule']}",
    )
    saved = (await am.automod.document())["rulesets"][0]["rules"][0]
    assert saved["name"] == "links"
    assert saved["triggers"] == [{"type": "invite"}, {"type": "regex", "pattern": "free nitro"}]
    assert [r.name for r in am.automod.snapshot.rules] == ["links", "words"]


@pytest.mark.asyncio
async def test_create_and_delete_rulesets_rules_and_lists(am: SimpleNamespace) -> None:
    response = await _post(am, "/automod/rulesets", {"name": "spam"})
    assert response.status == 302
    new_ruleset = response.headers["Location"].rsplit("/", 1)[1]

    response = await _post(am, f"/automod/rulesets/{new_ruleset}/rules", _rule_form("burst"))
    assert response.status == 302
    doc = await am.automod.document()
    [spam] = [r for r in doc["rulesets"] if r["name"] == "spam"]
    [burst] = spam["rules"]

    settings = [("name", "spam!"), ("conditions-0-type", "ignore_bots"), ("action", "save")]
    assert (await _post(am, f"/automod/rulesets/{new_ruleset}", settings)).status == 302
    doc = await am.automod.document()
    [spam] = [r for r in doc["rulesets"] if r["id"] == spam["id"]]
    assert (spam["name"], spam["enabled"], spam["conditions"]) == ("spam!", False, [{"type": "ignore_bots"}])

    assert (await _post(am, f"/automod/rules/{burst['id']}/delete")).status == 302
    assert (await _post(am, f"/automod/rulesets/{new_ruleset}/delete")).status == 302
    assert [r["name"] for r in (await am.automod.document())["rulesets"]] == ["invite"]

    response = await _post(am, "/automod/lists", {"name": "names"})
    list_path = response.headers["Location"]
    assert (await _post(am, list_path, {"name": "names", "words": "one\r\ntwo\r\n\r\n"})).status == 302
    [names] = [item for item in (await am.automod.document())["lists"] if item["name"] == "names"]
    assert names["words"] == ["one", "two"]
    assert (await _post(am, f"{list_path}/delete")).status == 302
    assert [item["name"] for item in (await am.automod.document())["lists"]] == ["slurs"]


@pytest.mark.asyncio
async def test_a_list_in_use_cannot_be_deleted(am: SimpleNamespace) -> None:
    response = await _post(am, "/automod/lists/900/delete")
    assert response.status == 400
    assert "This list is used by invite / words." in await response.text()
    assert len((await am.automod.document())["lists"]) == 1


@pytest.mark.asyncio
async def test_log_page_marks_dry_run_and_failures(am: SimpleNamespace) -> None:
    await am.automod.config.log.set(
        [
            {
                "at": 0,
                "event": "message",
                "user_id": 5,
                "user": "spammer",
                "channel_id": 10,
                "rules": [{"ruleset": "invite", "rule": "invite", "trigger": "Server invite"}],
                "actions": [
                    {"rule": "invite / invite", "type": "delete", "status": "would"},
                    {"rule": "invite / invite", "type": "mute", "status": "failed", "error": "Too high"},
                ],
                "dry_run": True,
            }
        ]
    )
    text = await (await am.client.get("/automod/log", headers=am.headers)).text()
    assert "delete: would have (dry-run)" in text
    assert "mute: failed <small>Too high</small>" in text
