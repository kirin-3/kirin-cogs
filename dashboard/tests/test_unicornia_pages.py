"""The Unicornia pages: profile, backgrounds and leaderboard on the member site, read-only views on the staff site.

A fake Unicornia cog stands in; the rules behind it are tested with the cog (unicornia/tests/test_background_shop.py).
"""

import secrets
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from dashboard.dashboard import SESSION_COOKIE, Session, _emojis
from dashboard.tests.test_member_site import (  # noqa: F401
    ACTIVE,
    CSRF,
    INACTIVE,
    REGULAR,
    STAFF,
    _get,
    _log_in,
    _post,
    ms,
)
from unicornia.database import DatabaseManager
from unicornia.market_views import portfolio_totals

BACKGROUNDS = [("default", "Default", 0, False), ("astolfo", "Astolfo", 20_000, False), ("aki", "Aki", 20_000, True)]
FORMER = 400000000000000009
MISSING_CHANNEL = 777


class _FakeUnicornia:
    def __init__(self) -> None:
        self.ranking: list[tuple[int, int]] = []
        self.equipped: dict[int, str] = {}
        self.owned: dict[int, set[str]] = {}
        self.wallets: dict[int, int] = {}
        self.transactions: list[dict[str, Any]] = []
        self.equipped_calls: list[list[int]] = []
        self.changes: list[tuple[str, int, str]] = []
        self.holdings: list[dict[str, Any]] = []
        self.dividends: list[dict[str, Any]] = []
        self.clubs: dict[int, dict[str, Any]] = {}
        self.invitations: list[dict[str, Any]] = []
        self.waifus: dict[int, dict[str, Any]] = {}
        self.config = SimpleNamespace(
            currency_name=AsyncMock(return_value="Slut points"), currency_symbol=AsyncMock(return_value="$")
        )

    level_stats = staticmethod(DatabaseManager.calculate_level_stats)

    async def xp_ranking(self, guild: Any) -> list[tuple[int, int]]:
        return list(self.ranking)

    async def equipped_backgrounds(self, user_ids: list[int]) -> dict[int, str]:
        self.equipped_calls.append(list(user_ids))
        return {user_id: self.equipped.get(user_id, "default") for user_id in user_ids}

    def background_images(self, key: str) -> tuple[str, str]:
        return f"https://unicornia.net/images/{key}.webp", f"https://unicornia.net/images/{key}-still.webp"

    async def backgrounds_for(self, member: Any) -> list[dict[str, Any]]:
        owned = self.owned.get(member.id, set()) | {"default"}
        equipped = self.equipped.get(member.id, "default")
        return [
            {
                "key": key,
                "name": name,
                "price": price,
                "animated": self.background_images(key)[0],
                "still": self.background_images(key)[1],
                "owned": key in owned,
                "equipped": key == equipped,
            }
            for key, name, price, hidden in BACKGROUNDS
            if not hidden or key in owned
        ]

    async def buy_background(self, member: Any, key: str) -> str:
        if self.wallets.get(member.id, 0) < 20_000:
            raise ValueError(f"Insufficient Slut points! You have {self.wallets.get(member.id, 0):,} but need 20,000.")
        self.changes.append(("buy", member.id, key))
        return key

    async def use_background(self, member: Any, key: str) -> str:
        if key not in self.owned.get(member.id, set()):
            raise ValueError(f"You don't own the background `{key}`.")
        self.changes.append(("use", member.id, key))
        return key

    async def get_balance(self, user_id: int) -> tuple[int, int]:
        return self.wallets.get(user_id, 0), 0

    async def member_summary(
        self, guild: Any, user_id: int, *, transactions: int = 20, details: bool = False
    ) -> dict[str, Any]:
        rank = next((n + 1 for n, (ranked, _) in enumerate(self.ranking) if ranked == user_id), None)
        background = self.equipped.get(user_id, "default")
        summary: dict[str, Any] = {
            "wallet": self.wallets.get(user_id, 0),
            "bank": 20,
            "xp": self.level_stats(dict(self.ranking).get(user_id, 0)),
            "rank": rank,
            "club": None,
            "background": background,
            "background_name": background.title(),
            "transactions": [dict(t) for t in self.transactions[:transactions]],
        }
        if details:
            summary |= {"rakeback": 42, "bets": [], "inventory": [], "owned_backgrounds": ["default"]}
        return summary

    async def richest(self, guild: Any, limit: int = 25) -> list[tuple[int, int]]:
        return [(ACTIVE, 90_000)]

    async def house_stats(self) -> dict[str, Any]:
        game = {"feature": "slots", "rounds": 1_234, "staked": 50_000, "rtp": 0.975, "deviation": 0.0}
        game |= {"off_target": False, "low_confidence": False, "epoch": "2026-01-01"}
        pool = {"balance": 3_000, "lifetime_house_banked": 1, "lifetime_pooled": 2, "lifetime_trade_tax": 3}
        pool |= {"next_distribution_at": None}
        return {"target": 0.975, "games": [game], "pool": pool, "runs": []}

    async def config_snapshot(self, guild: Any) -> dict[str, Any]:
        return {
            "settings": {"timely_amount": 500},
            "generation_channels": [MISSING_CHANNEL],
            "xp_channels": [],
            "double_xp_channels": [],
            "excluded_roles": [],
            "command_whitelist": {"bet": [MISSING_CHANNEL]},
            "system_whitelist": {},
            "market_channel": None,
            "role_rewards": [],
            "currency_rewards": [(5, 1_000)],
        }

    async def stocks(self) -> list[dict[str, Any]]:
        return [{"symbol": "UNI", "name": "Unicorn", "price": 12.5, "previous_price": 10.0}]

    async def portfolio(self, user_id: int) -> dict[str, Any]:
        holdings = self.holdings if user_id == REGULAR else []
        return {
            "holdings": [{**h, **portfolio_totals([h])} for h in holdings],
            "totals": portfolio_totals(holdings),
            "dividends": self.dividends if user_id == REGULAR else [],
        }

    async def club_for(self, user_id: int) -> dict[str, Any]:
        club = self.clubs.get(user_id)
        return {"club": club, "invitations": [] if club else list(self.invitations)}

    async def waifu_status(self, user_id: int) -> dict[str, Any]:
        empty = {"claimer_id": None, "affinity_id": None, "affinity_from": [], "waifus": [], "gifts": []}
        return self.waifus.get(user_id, {"price": 50, **empty})


@pytest.fixture
def uni(ms: SimpleNamespace) -> _FakeUnicornia:  # noqa: F811
    fake = _FakeUnicornia()
    ms.cogs["Unicornia"] = fake
    for member in ms.members.values():
        member.name = f"user{member.id % 10}"
        member.bot = False
        member.display_avatar.with_size.return_value.url = "https://cdn.discordapp.com/avatars/1/a.png"
    ms.guild.members = list(ms.members.values())
    ms.guild.get_channel_or_thread.return_value = None
    return fake


# --- member site ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_member_sees_the_unicornia_pages(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    _, home = await _get(ms, REGULAR, "/")

    for path in ("/me", "/me/backgrounds", "/me/stocks", "/me/club", "/me/waifu", "/leaderboard"):
        assert f'href="{path}"' in home


@pytest.mark.asyncio
async def test_unicornia_pages_hide_and_refuse_when_the_cog_is_unloaded(ms: SimpleNamespace) -> None:  # noqa: F811
    _, home = await _get(ms, REGULAR, "/")
    paths = ("/me", "/me/backgrounds", "/me/stocks", "/me/club", "/me/waifu", "/leaderboard")
    statuses = [(await _get(ms, REGULAR, path))[0] for path in paths]
    buy = await _post(ms, REGULAR, "/me/backgrounds/buy", {"key": "astolfo"})

    assert 'href="/me' not in home and 'href="/leaderboard"' not in home
    assert statuses == [503] * 6 and buy.status == 503


@pytest.mark.asyncio
async def test_member_csp_allows_exactly_self_discord_and_unicornia_images(ms: SimpleNamespace) -> None:  # noqa: F811
    response = await ms.client.get("/", headers=_log_in(ms, REGULAR))

    img_src = next(p for p in response.headers["Content-Security-Policy"].split("; ") if p.startswith("img-src"))
    assert img_src == "img-src 'self' https://cdn.discordapp.com https://unicornia.net"


@pytest.mark.asyncio
async def test_profile_shows_the_members_own_numbers(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.ranking = [(n, 100_000 - n) for n in range(1, 7)] + [(REGULAR, 5_000)]
    uni.wallets[REGULAR] = 1_500
    uni.equipped[REGULAR] = "astolfo"
    uni.transactions = [{"type": "timely", "amount": 500, "reason": "Daily reward", "date": "2026-09-01 10:00:00"}]

    status, page = await _get(ms, REGULAR, "/me")

    assert status == 200
    assert "#7" in page and "1,500" in page and f"Level {uni.level_stats(5_000).level}" in page
    assert 'src="https://unicornia.net/images/astolfo.webp"' in page
    assert "Daily reward" in page and '<time datetime="2026-09-01T10:00:00+00:00">' in page


@pytest.mark.asyncio
async def test_profile_of_a_member_with_nothing_yet(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    status, page = await _get(ms, REGULAR, "/me")

    assert status == 200
    assert "Not ranked yet" in page and "No transactions yet." in page and "Level 0" in page
    assert "images/default.webp" in page


@pytest.mark.asyncio
async def test_profile_rank_past_300_reads_300_plus(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.ranking = [(n, 1_000_000 - n) for n in range(1, 301)]

    _, page = await _get(ms, REGULAR, "/me")

    assert "300+" in page


@pytest.mark.asyncio
async def test_backgrounds_page_confirms_prices_and_hides_unowned_hidden(
    ms: SimpleNamespace,  # noqa: F811
    uni: _FakeUnicornia,
) -> None:
    uni.wallets[REGULAR] = 25_000
    _, page = await _get(ms, REGULAR, "/me/backgrounds")
    uni.owned[ACTIVE] = {"aki"}
    _, owner = await _get(ms, ACTIVE, "/me/backgrounds")

    assert 'data-confirm="Buy Astolfo for 20,000 Slut points?' in page and "25,000 Slut points" in page
    assert "Aki" not in page
    assert 'value="aki"' in owner and "Equip" in owner


@pytest.mark.asyncio
async def test_buying_acts_on_the_member_whatever_the_form_says(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.wallets[REGULAR] = 25_000

    response = await _post(ms, REGULAR, "/me/backgrounds/buy", {"key": "astolfo", "user_id": str(ACTIVE)})

    assert (response.status, response.headers["Location"]) == (302, "/me/backgrounds")
    assert uni.changes == [("buy", REGULAR, "astolfo")]


@pytest.mark.asyncio
async def test_refused_buy_shows_the_reason_with_400(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    response = await _post(ms, REGULAR, "/me/backgrounds/buy", {"key": "astolfo"})

    assert response.status == 400
    assert "Insufficient Slut points! You have 0 but need 20,000." in await response.text()
    assert uni.changes == []


@pytest.mark.asyncio
async def test_equip_and_refusal(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.owned[REGULAR] = {"aki"}

    done = await _post(ms, REGULAR, "/me/backgrounds/use", {"key": "aki"})
    refused = await _post(ms, REGULAR, "/me/backgrounds/use", {"key": "astolfo"})

    assert done.status == 302 and refused.status == 400
    assert "You don&#39;t own the background `astolfo`." in await refused.text()
    assert uni.changes == [("use", REGULAR, "aki")]


@pytest.mark.asyncio
async def test_background_posts_need_the_csrf_token(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.wallets[REGULAR] = 25_000
    for path in ("/me/backgrounds/buy", "/me/backgrounds/use"):
        response = await ms.client.post(path, data={"key": "astolfo"}, headers=_log_in(ms, REGULAR))
        assert response.status == 403
    assert uni.changes == []


@pytest.mark.asyncio
async def test_leaderboard_pages_and_the_viewers_rank(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.ranking = [(n, 100_000 - n) for n in range(1, 60)] + [(REGULAR, 10)]
    uni.equipped[1] = "astolfo"

    _, first = await _get(ms, REGULAR, "/leaderboard")
    _, last = await _get(ms, REGULAR, "/leaderboard?page=999")
    _, junk = await _get(ms, REGULAR, "/leaderboard?page=abc")

    assert "You're #60" in first and 'href="/leaderboard?page=3">Show me' in first
    assert 'src="https://unicornia.net/images/astolfo-still.webp"' in first
    assert 'data-animated="https://unicornia.net/images/astolfo.webp"' in first
    assert first.count('class="lb-row') == 25 and "#25" in first and "#26" not in first
    assert "Page 3 of 3" in last and 'class="lb-row me"' in last and "Show me" not in last
    assert "Page 1 of 3" in junk
    assert [len(call) for call in uni.equipped_calls] == [25, 10, 25]


@pytest.mark.asyncio
async def test_empty_leaderboard(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    status, page = await _get(ms, REGULAR, "/leaderboard")

    assert status == 200 and "Nobody has any XP yet." in page and "Not ranked yet" in page


@pytest.mark.asyncio
async def test_account_tabs_on_every_me_page(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    for path in ("/me", "/me/backgrounds", "/me/stocks", "/me/club", "/me/waifu"):
        _, page = await _get(ms, REGULAR, path)
        assert f'<a href="{path}" class="on">' in page and 'aria-label="Your account"' in page, path
        assert 'href="/me/stocks"' in page and 'href="/me/warnings"' not in page, path  # Moderation isn't loaded


@pytest.mark.asyncio
async def test_stocks_page_shows_holdings_totals_and_dividends(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.holdings = [
        {
            "symbol": "UNI",
            "name": "Unicorn",
            "emoji": "<a:laugh:691625827938336818>",
            "amount": 10,
            "average_cost": 100,
            "current_price": 120,
        }
    ]
    uni.dividends = [
        {"period_end": "2026-09-02", "symbol": "UNI", "weight": 0.5, "amount": 30, "date": ""},
        {"period_end": "2026-09-01", "symbol": "UNI", "weight": 0.25, "amount": 15, "date": ""},
    ]  # fmt: skip

    status, page = await _get(ms, REGULAR, "/me/stocks")
    _, empty = await _get(ms, ACTIVE, "/me/stocks")

    assert status == 200 and "Unicorn" in page and "1,200" in page and "+200" in page and "+20.0%" in page
    assert page.index("2026-09-02") < page.index("2026-09-01") and "0.250" in page
    assert (
        '<img class="inline-emoji" src="https://cdn.discordapp.com/emojis/691625827938336818.gif" alt=":laugh:"' in page
    )
    assert "&lt;a:laugh" not in page
    assert "You don't hold any shares." in empty and "You haven't received any dividends." in empty


@pytest.mark.asyncio
async def test_club_page_lists_members_with_owner_and_admins(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    members = [
        {"user_id": ACTIVE, "name": "stale", "xp": 900, "owner": True, "admin": False},
        {"user_id": FORMER, "name": "gone_user", "xp": 50, "owner": False, "admin": True},
        {"user_id": FORMER + 1, "name": None, "xp": 5, "owner": False, "admin": False},
        {"user_id": REGULAR, "name": "me", "xp": 10, "owner": False, "admin": False},
    ]
    uni.clubs[REGULAR] = {
        "name": "Sparkles", "description": "Shiny", "xp": 12_345, "owner_id": ACTIVE, "rank": 3, "members": members,
        "image_url": "https://cdn.discordapp.com/icons/1/a.png", "banner_url": "https://i.imgur.com/banner.png",
    }  # fmt: skip

    status, page = await _get(ms, REGULAR, "/me/club")

    assert status == 200 and "Sparkles" in page and "12,345" in page and "#3" in page
    assert ms.members[ACTIVE].display_name in page and "stale" not in page
    assert "gone_user" in page and "Unknown user" in page and "Owner" in page and "Admin" in page
    assert '<img class="club-icon" src="https://cdn.discordapp.com/icons/1/a.png"' in page
    assert '<a href="https://i.imgur.com/banner.png" rel="noreferrer noopener"' in page
    assert 'src="https://i.imgur.com' not in page


@pytest.mark.asyncio
async def test_club_page_without_a_club(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    _, nothing = await _get(ms, REGULAR, "/me/club")
    uni.invitations = [{"name": "Sparkles", "description": "Shiny"}]
    _, invited = await _get(ms, REGULAR, "/me/club")

    assert "not in a club." in nothing and "You have no club invitations." in nothing
    assert "Invitations" in invited and "Sparkles" in invited


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "https://unicornia.net.evil.example/a.png", "http://unicornia.net/a.png"]
)
@pytest.mark.asyncio
async def test_club_images_load_only_from_allowed_https_hosts(
    ms: SimpleNamespace,  # noqa: F811
    uni: _FakeUnicornia,
    url: str,
) -> None:
    uni.clubs[REGULAR] = {
        "name": "Sparkles", "description": "", "xp": 0, "owner_id": REGULAR, "rank": 1, "members": [],
        "image_url": url, "banner_url": "",
    }  # fmt: skip

    _, page = await _get(ms, REGULAR, "/me/club")

    assert f'src="{url}' not in page and "javascript:" not in page


@pytest.mark.asyncio
async def test_waifu_page_of_a_claimed_member(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.config.currency_symbol.return_value = "<:slut:686148402941001730>"
    uni.waifus[REGULAR] = {
        "price": 500,
        "claimer_id": ACTIVE,
        "affinity_id": INACTIVE,
        "affinity_from": [INACTIVE, FORMER],
        "waifus": [{"user_id": 500_000_000_000_000_000 + n, "price": 70 + n} for n in range(14)],
        "gifts": [
            {"name": "Rose", "emoji": "🌹", "count": 3},
            {"name": "Cage", "emoji": "<:cage:686126928327213057>", "count": 1},
        ],
    }

    status, page = await _get(ms, REGULAR, "/me/waifu")

    assert (
        status == 200
        and 'src="https://cdn.discordapp.com/emojis/686148402941001730.webp" alt=":slut:" title=":slut:">500<' in page
    )
    assert page.count('src="https://cdn.discordapp.com/emojis/686148402941001730.webp"') == 15 and "&lt;:" not in page
    assert (
        '<img class="inline-emoji" src="https://cdn.discordapp.com/emojis/686126928327213057.webp" alt=":cage:"' in page
    )
    assert ms.members[ACTIVE].display_name in page and ms.members[INACTIVE].display_name in page
    assert "Your waifus (14)" in page and page.count("Unknown user") == 15 and ">83<" in page
    assert "🌹 Rose <small>\N{MULTIPLICATION SIGN}3</small>" in page and "Gifts received (4)" in page


def test_emojis_filter_turns_discord_markup_into_images_and_escapes_the_rest() -> None:
    html = str(_emojis('<b>hi</b> <:w_yay:686136240566829112> & <a:laugh:691625827938336818> <:x:1> "q"'))

    assert html.startswith("&lt;b&gt;hi&lt;/b&gt; <img")
    assert 'src="https://cdn.discordapp.com/emojis/686136240566829112.webp" alt=":w_yay:"' in html
    assert 'src="https://cdn.discordapp.com/emojis/691625827938336818.gif"' in html
    assert "&amp;" in html and "&lt;:x:1&gt;" in html and "&#34;q&#34;" in html
    assert str(_emojis(None)) == "" and str(_emojis("🦄")) == "🦄"


@pytest.mark.asyncio
async def test_waifu_page_of_a_member_never_claimed(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    status, page = await _get(ms, REGULAR, "/me/waifu")

    assert status == 200 and "$50" in page and page.count(">Nobody</p>") == 2 and "Your waifus (0)" in page


# --- staff site ----------------------------------------------------------------------------------

STAFF_PAGES = [
    "/unicornia/members",
    f"/unicornia/members/{REGULAR}",
    "/unicornia/economy",
    "/unicornia/config",
    "/unicornia/market",
]


def _staff(ms: SimpleNamespace) -> dict[str, str]:  # noqa: F811
    token = secrets.token_urlsafe(32)
    ms.cog.sessions[token] = Session(STAFF, CSRF, time.monotonic() + 3600)
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


async def _staff_get(ms: SimpleNamespace, path: str) -> tuple[int, str]:  # noqa: F811
    response = await ms.staff.get(path, headers=_staff(ms), allow_redirects=False)
    return response.status, await response.text()


@pytest.mark.asyncio
async def test_staff_pages_open_to_non_owner_staff_and_only_by_get(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    ms.bot.is_owner = AsyncMock(return_value=False)
    for path in STAFF_PAGES:
        status, page = await _staff_get(ms, path)
        assert status == 200, path
        assert 'class="subnav"' in page
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            response = await ms.staff.request(method, path, data={"csrf": CSRF}, headers=_staff(ms))
            assert response.status in (404, 405), (method, path)
    assert uni.changes == []


@pytest.mark.asyncio
async def test_staff_pages_503_without_the_cog(ms: SimpleNamespace) -> None:  # noqa: F811
    for path in STAFF_PAGES:
        assert (await _staff_get(ms, path))[0] == 503, path


@pytest.mark.asyncio
async def test_member_search(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    ms.members[REGULAR].display_name = "Kirin"
    ms.members[ACTIVE].name = "kiriko"

    _, page = await _staff_get(ms, "/unicornia/members?q=KIRI")
    status, _ = await _staff_get(ms, f"/unicornia/members?q={FORMER}")

    assert f'href="/unicornia/members/{REGULAR}"' in page and f'href="/unicornia/members/{ACTIVE}"' in page
    assert f'href="/unicornia/members/{STAFF}"' not in page
    assert status == 302


@pytest.mark.asyncio
async def test_former_member_and_member_with_no_data(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    uni.wallets[FORMER] = 12_345
    uni.transactions = [{"type": "give", "amount": -5, "reason": "gift", "date": "2026-09-01 10:00:00"}]

    _, former = await _staff_get(ms, f"/unicornia/members/{FORMER}")
    uni.transactions = []
    _, empty = await _staff_get(ms, "/unicornia/members/5")

    assert "12,345" in former and "Not in the server" in former and "gift" in former and "Pending rakeback" in former
    assert "No transactions." in empty and "No bets." in empty


@pytest.mark.asyncio
async def test_economy_config_and_market_pages(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:  # noqa: F811
    _, economy = await _staff_get(ms, "/unicornia/economy")
    _, config = await _staff_get(ms, "/unicornia/config")
    _, market = await _staff_get(ms, "/unicornia/market")

    assert "97.500%" in economy and "1,234" in economy and "90,000" in economy and "3,000" in economy
    assert f"{MISSING_CHANNEL} (missing)" in config and "Timely amount" in config and "nadeko" not in config.lower()
    assert "Level 5: 1,000 currency" in config
    assert "UNI" in market and "+25.00%" in market
    assert (economy + config + market).count("<form") == 3  # only the log-out buttons


def test_fake_matches_the_cog() -> None:
    """The fake has every method the pages call on the real cog, with the same names."""
    from unicornia.unicornia import Unicornia

    for name in vars(_FakeUnicornia):
        if not name.startswith("_") and name != "config":
            assert hasattr(Unicornia, name), name
