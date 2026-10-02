"""The roleplay gifs for the member site: paging and pools, thumbs up and down, and deleting a member's votes."""

from pathlib import Path
from typing import cast

import pytest
import simcord
from redbot.core.bot import Red

from roleplay.gifs import page_of
from roleplay.main import Roleplay


def test_pages_hold_the_size_and_the_last_one_is_short() -> None:
    items = list(range(12))

    assert page_of(items, 1, 5) == ([0, 1, 2, 3, 4], 1, 3)
    assert page_of(items, 2, 5) == ([5, 6, 7, 8, 9], 2, 3)
    assert page_of(items, 3, 5) == ([10, 11], 3, 3)


def test_a_page_past_the_end_shows_the_last_and_one_before_the_start_the_first() -> None:
    items = list(range(12))

    assert page_of(items, 99, 5)[1:] == (3, 3)
    assert page_of(items, 0, 5)[1] == 1
    assert page_of(items, -4, 5)[1] == 1


def test_no_items_is_one_empty_page() -> None:
    assert page_of([], 1, 5) == ([], 1, 1)
    assert page_of([], 7, 5) == ([], 1, 1)


@pytest.fixture
def red_cogs() -> list[str]:
    return ["roleplay"]


def _files(root: Path, action: str, *names: str) -> None:
    for name in names:
        path = root / action / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"GIF89a")


@pytest.fixture
def images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The images folder: bite has the five-file example, bow has two."""
    _files(tmp_path, "bite", "bite_a.gif", "bite_mlw_b.gif", "bite_wlm_c.gif", "bite_wlw_d.gif", "bite_mlm_e.gif")
    _files(tmp_path, "bow", "bow_1.gif", "bow_2.gif")
    monkeypatch.setattr(Roleplay, "images_path", property(lambda _self: tmp_path))
    return tmp_path


def _cog(env: simcord.Env) -> Roleplay:
    cog = cast(Red, env.bot).get_cog("Roleplay")
    assert isinstance(cog, Roleplay)
    return cog


def _names(page: dict) -> list[str]:
    return [gif["name"] for gif in page["gifs"]]


@pytest.mark.asyncio
async def test_pools_split_the_way_the_bot_picks(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)

    default = await cog.gif_page("bite", "default", 1, 1)
    wlw = await cog.gif_page("bite", "wlw", 1, 1)
    mlm = await cog.gif_page("bite", "mlm", 1, 1)

    assert _names(default) == ["bite_a.gif", "bite_mlw_b.gif", "bite_wlm_c.gif"]
    assert _names(wlw) == ["bite_wlw_d.gif"]
    assert _names(mlm) == ["bite_mlm_e.gif"]
    assert (default["page"], default["pages"]) == (1, 1)
    # every pool's page says how many gifs each pool has, for the tabs
    assert default["counts"] == wlw["counts"] == mlm["counts"] == {"default": 3, "wlw": 1, "mlm": 1}


@pytest.mark.asyncio
async def test_gifs_with_eros_in_the_name_are_flagged_as_ai(red_env: simcord.Env, images: Path) -> None:
    _files(images, "bow", "bow_eros_3.gif", "bow_MLM_eros8_4.gif")

    page = await _cog(red_env).gif_page("bow", "default", 1, 1)

    assert {gif["name"]: gif["ai"] for gif in page["gifs"]} == {
        "bow_1.gif": False,
        "bow_2.gif": False,
        "bow_eros_3.gif": True,
    }
    assert [gif["ai"] for gif in (await _cog(red_env).gif_page("bow", "mlm", 1, 1))["gifs"]] == [True]


@pytest.mark.asyncio
async def test_actions_list_every_action_with_its_gif_count(red_env: simcord.Env, images: Path) -> None:
    actions = await _cog(red_env).gif_actions()

    names = [action["name"] for action in actions]
    assert names == sorted(names) and len(names) == 29
    counts = {action["name"]: action["count"] for action in actions}
    assert counts["bite"] == 5 and counts["bow"] == 2 and counts["suck"] == 0


@pytest.mark.asyncio
async def test_empty_pool_is_one_empty_page(red_env: simcord.Env, images: Path) -> None:
    page = await _cog(red_env).gif_page("suck", "wlw", 1, 1)

    assert page == {"gifs": [], "page": 1, "pages": 1, "counts": {"default": 0, "wlw": 0, "mlm": 0}}


@pytest.mark.asyncio
async def test_unknown_action_or_pool_is_a_lookup_error(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)

    with pytest.raises(LookupError):
        await cog.gif_page("notanaction", "default", 1, 1)
    with pytest.raises(LookupError):
        await cog.gif_page("bite", "mlw", 1, 1)  # a tag, not a pool
    with pytest.raises(LookupError):
        await cog.gif_page("../bite", "default", 1, 1)


@pytest.mark.asyncio
async def test_second_page_of_twelve_shows_the_sixth_to_tenth(red_env: simcord.Env, images: Path) -> None:
    _files(images, "slap", *(f"slap_{n:02}.gif" for n in range(12)))

    page = await _cog(red_env).gif_page("slap", "default", 1, 2)

    assert _names(page) == [f"slap_{n:02}.gif" for n in range(5, 10)]
    assert (page["page"], page["pages"]) == (2, 3)


@pytest.mark.asyncio
async def test_a_file_added_later_shows_on_the_next_call(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)
    assert _names(await cog.gif_page("bow", "default", 1, 1)) == ["bow_1.gif", "bow_2.gif"]

    _files(images, "bow", "bow_0.gif")

    assert _names(await cog.gif_page("bow", "default", 1, 1)) == ["bow_0.gif", "bow_1.gif", "bow_2.gif"]


@pytest.mark.asyncio
async def test_a_gif_name_is_only_looked_up_never_joined_onto_a_path(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)
    (images / "secret.txt").write_text("no")

    assert await cog.gif_path("bite", "bite_a.gif") == images / "bite" / "bite_a.gif"
    for name in ("../x.gif", "../secret.txt", r"..\secret.txt", "bite_zzz.gif", "", "bite_a.GIF"):
        assert await cog.gif_path("bite", name) is None, name
    assert await cog.gif_path("notanaction", "bite_a.gif") is None


async def _raw_votes(cog: Roleplay, action: str, name: str) -> object:
    return await cog.config.custom("GIF_VOTES", action, name).votes()


@pytest.mark.asyncio
async def test_a_new_vote_replaces_the_old_one_and_none_takes_it_back(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)

    await cog.gif_votes.set(7, "bite", "bite_a.gif", 1)
    assert await _raw_votes(cog, "bite", "bite_a.gif") == {"7": 1}
    await cog.gif_votes.set(7, "bite", "bite_a.gif", -1)
    assert await _raw_votes(cog, "bite", "bite_a.gif") == {"7": -1}
    assert await cog.gif_votes.totals() == {("bite", "bite_a.gif"): (0, 1)}

    await cog.gif_votes.set(7, "bite", "bite_a.gif", 0)
    assert await _raw_votes(cog, "bite", "bite_a.gif") == {}
    assert await cog.gif_votes.totals() == {}


@pytest.mark.asyncio
async def test_a_value_that_is_not_a_vote_is_refused(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)

    with pytest.raises(ValueError):
        await cog.gif_votes.set(7, "bite", "bite_a.gif", 5)
    assert await cog.gif_votes.totals() == {}


@pytest.mark.asyncio
async def test_forget_removes_only_that_members_votes(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)
    for user in (1, 2):
        await cog.gif_votes.set(user, "bite", "bite_a.gif", 1)
        await cog.gif_votes.set(user, "bow", "bow_1.gif", -1)
    await cog.gif_votes.set(1, "bow", "bow_2.gif", 1)

    await cog.gif_votes.forget(1)

    assert await cog.gif_votes.totals() == {("bite", "bite_a.gif"): (1, 0), ("bow", "bow_1.gif"): (0, 1)}
    assert await cog.gif_votes.mine(1, "bite", ["bite_a.gif"]) == {}
    assert await cog.gif_votes.mine(2, "bite", ["bite_a.gif"]) == {"bite_a.gif": 1}


@pytest.mark.asyncio
async def test_malformed_stored_records_are_skipped_not_counted(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)
    votes = cog.config.custom("GIF_VOTES")
    await votes.set_raw("bite", "text.gif", value="junk")  # the whole record is a string
    await votes.set_raw("bite", "notdict.gif", value={"votes": "junk"})
    await votes.set_raw("bite", "badvalue.gif", value={"votes": {"1": 5, "2": True, "x": 1, "3": "1"}})
    await votes.set_raw("bow", value="junk")  # the whole action is a string
    await votes.set_raw("bite", "mixed.gif", value={"votes": {"4": 1, "1": 5}})

    assert await cog.gif_votes.totals() == {("bite", "mixed.gif"): (1, 0)}
    assert await cog.gif_votes.mine(1, "bite", ["text.gif", "notdict.gif", "badvalue.gif", "mixed.gif"]) == {}
    await cog.gif_votes.forget(1)  # the malformed entry under this member's own ID goes too
    assert await _raw_votes(cog, "bite", "badvalue.gif") == {}
    assert await cog.gif_votes.totals() == {("bite", "mixed.gif"): (1, 0)}


@pytest.mark.asyncio
async def test_a_vote_for_a_missing_file_stores_nothing(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)

    for action, name in (("bite", "bite_zzz.gif"), ("bite", "../bow/bow_1.gif"), ("notanaction", "bite_a.gif")):
        with pytest.raises(LookupError):
            await cog.gif_vote(7, action, name, 1)

    assert await cog.gif_votes.totals() == {}


@pytest.mark.asyncio
async def test_the_page_shows_the_viewers_own_vote(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)
    await cog.gif_vote(7, "bite", "bite_a.gif", 1)
    await cog.gif_vote(8, "bite", "bite_a.gif", -1)
    await cog.gif_vote(8, "bite", "bite_mlw_b.gif", -1)

    mine = {gif["name"]: gif["mine"] for gif in (await cog.gif_page("bite", "default", 7, 1))["gifs"]}
    theirs = {gif["name"]: gif["mine"] for gif in (await cog.gif_page("bite", "default", 8, 1))["gifs"]}
    nobody = {gif["name"]: gif["mine"] for gif in (await cog.gif_page("bite", "default", 9, 1))["gifs"]}

    assert mine == {"bite_a.gif": 1, "bite_mlw_b.gif": 0, "bite_wlm_c.gif": 0}
    assert theirs == {"bite_a.gif": -1, "bite_mlw_b.gif": -1, "bite_wlm_c.gif": 0}
    assert set(nobody.values()) == {0}


@pytest.mark.asyncio
async def test_totals_list_the_lowest_score_first(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)
    await cog.gif_vote(1, "bite", "bite_a.gif", 1)  # 1 up, 4 down: score -3
    for user in (2, 3, 4, 5):
        await cog.gif_vote(user, "bite", "bite_a.gif", -1)
    for user in range(1, 6):  # 5 up: score 5
        await cog.gif_vote(user, "bow", "bow_1.gif", 1)
    await cog.gif_vote(1, "bow", "bow_2.gif", 1)  # 1 up: score 1
    await cog.gif_vote(1, "bite", "bite_wlw_d.gif", 1)  # 1 up: same score, the same votes, so action and name decide

    totals = await cog.gif_vote_totals()

    assert [(row["action"], row["name"], row["up"], row["down"]) for row in totals] == [
        ("bite", "bite_a.gif", 1, 4),
        ("bite", "bite_wlw_d.gif", 1, 0),
        ("bow", "bow_2.gif", 1, 0),
        ("bow", "bow_1.gif", 5, 0),
    ]


@pytest.mark.asyncio
async def test_totals_leave_out_taken_back_and_deleted_gifs(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)
    await cog.gif_vote(1, "bite", "bite_a.gif", 1)
    await cog.gif_vote(1, "bite", "bite_a.gif", 0)  # taken back
    await cog.gif_vote(1, "bow", "bow_1.gif", 1)
    await cog.gif_vote(1, "bow", "bow_2.gif", -1)
    (images / "bow" / "bow_2.gif").unlink()  # deleted or renamed by hand

    totals = await cog.gif_vote_totals()

    assert [(row["action"], row["name"]) for row in totals] == [("bow", "bow_1.gif")]
    assert await cog.gif_votes.totals() == {("bow", "bow_1.gif"): (1, 0), ("bow", "bow_2.gif"): (0, 1)}


@pytest.mark.asyncio
async def test_deleting_a_members_data_removes_their_votes_only(red_env: simcord.Env, images: Path) -> None:
    cog = _cog(red_env)
    gifs = [("bite", "bite_a.gif"), ("bite", "bite_wlw_d.gif"), ("bow", "bow_1.gif")]
    for user in (1, 2):
        for action, name in gifs:
            await cog.gif_vote(user, action, name, 1)

    await cog.red_delete_data_for_user(requester="user", user_id=1)

    assert await cog.gif_votes.totals() == {gif: (1, 0) for gif in gifs}
    for action, name in gifs:
        assert await cog.gif_votes.mine(1, action, [name]) == {}
        assert await cog.gif_votes.mine(2, action, [name]) == {name: 1}
