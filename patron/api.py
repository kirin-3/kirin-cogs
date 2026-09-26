"""Patreon API v2 client and Buy Me a Coffee webhook signature check."""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import aiohttp

PATREON_API = "https://www.patreon.com/api/oauth2/v2"
PATREON_TOKEN_URL = "https://www.patreon.com/api/oauth2/token"
MEMBER_FIELDS = (
    "full_name,email,patron_status,last_charge_date,last_charge_status,currently_entitled_amount_cents,pledge_cadence"
)


class ApiError(Exception):
    """A payment API could not be reached or refused the request."""


@dataclass(frozen=True)
class PatreonMember:
    id: str
    name: str
    email: str
    discord_id: int | None
    status: str | None  # active_patron, declined_patron, former_patron, or None for free members
    last_charge_date: str | None
    last_charge_status: str | None
    cents: int
    cadence: int  # months covered by one charge


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def parse_members_page(payload: dict[str, Any]) -> list[PatreonMember]:
    """Turn one JSON:API page of campaign members into PatreonMember rows."""
    users = {
        user.get("id"): user.get("attributes") or {}
        for user in payload.get("included") or []
        if isinstance(user, dict) and user.get("type") == "user"
    }
    members = []
    for row in payload.get("data") or []:
        attrs = row.get("attributes") or {}
        user_id = (((row.get("relationships") or {}).get("user") or {}).get("data") or {}).get("id")
        discord = ((users.get(user_id) or {}).get("social_connections") or {}).get("discord") or {}
        raw_id = str(discord.get("user_id") or "")
        members.append(
            PatreonMember(
                id=str(row["id"]),
                name=str(attrs.get("full_name") or ""),
                email=normalize_email(attrs.get("email")),
                discord_id=int(raw_id) if raw_id.isdigit() else None,
                status=attrs.get("patron_status"),
                last_charge_date=attrs.get("last_charge_date"),
                last_charge_status=attrs.get("last_charge_status"),
                cents=int(attrs.get("currently_entitled_amount_cents") or 0),
                cadence=max(1, int(attrs.get("pledge_cadence") or 1)),
            )
        )
    return members


class PatreonClient:
    """Reads campaign members with the creator's token, refreshing it when it expires.

    Tokens live in Red's shared API tokens under ``patreon``: access_token, refresh_token, client_id, client_secret.
    """

    def __init__(self, bot: Any, session: aiohttp.ClientSession) -> None:
        self.bot = bot
        self.session = session
        self._campaign_id: str | None = None

    async def members(self) -> list[PatreonMember]:
        url: str | None = f"{PATREON_API}/campaigns/{await self._campaign()}/members"
        params: dict[str, str] | None = {
            "include": "user",
            "fields[member]": MEMBER_FIELDS,
            "fields[user]": "social_connections",
            "page[count]": "1000",
        }
        members: list[PatreonMember] = []
        while url:
            payload = await self._get(url, params)
            members += parse_members_page(payload)
            url = (payload.get("links") or {}).get("next")
            params = None  # the next link carries the query and cursor
        return members

    async def _campaign(self) -> str:
        if self._campaign_id is None:
            campaigns = (await self._get(f"{PATREON_API}/campaigns", None)).get("data") or []
            if not campaigns:
                raise ApiError("The Patreon token has no campaign.")
            self._campaign_id = str(campaigns[0]["id"])
        return self._campaign_id

    async def _get(self, url: str, params: dict[str, str] | None) -> dict[str, Any]:
        for attempt in range(2):
            tokens = await self.bot.get_shared_api_tokens("patreon")
            if not tokens.get("access_token"):
                raise ApiError("Patreon tokens are not set. See `[p]patronset creds`.")
            headers = {"Authorization": f"Bearer {tokens['access_token']}"}
            async with self.session.get(url, params=params, headers=headers) as resp:
                if resp.status == 401 and attempt == 0:
                    await self._refresh(tokens)
                    continue
                if resp.status != 200:
                    raise ApiError(f"Patreon returned HTTP {resp.status}.")
                return await resp.json()
        raise ApiError("Patreon rejected the refreshed token.")

    async def _refresh(self, tokens: dict[str, str]) -> None:
        missing = [key for key in ("refresh_token", "client_id", "client_secret") if not tokens.get(key)]
        if missing:
            raise ApiError(f"The Patreon access token expired and {', '.join(missing)} is not set.")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
            "client_secret": tokens["client_secret"],
        }
        async with self.session.post(PATREON_TOKEN_URL, data=data) as resp:
            if resp.status != 200:
                raise ApiError(f"Patreon token refresh failed (HTTP {resp.status}).")
            body = await resp.json()
        # Patreon rotates the refresh token; the old one stops working.
        await self.bot.set_shared_api_tokens(
            "patreon", access_token=body["access_token"], refresh_token=body["refresh_token"]
        )


def verify_bmc_signature(body: bytes, secret: str, signature: str) -> bool:
    """Check Buy Me a Coffee's x-signature-sha256 header: hex HMAC-SHA256 of the raw body."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.strip().lower().encode())
