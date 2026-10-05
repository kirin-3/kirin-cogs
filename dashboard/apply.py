"""The staff application on the member site: a form for Level 30+ members, posted to the staff's applications channel.

The answers go straight to Discord and are not stored. Only the time of a member's last application is kept, in memory,
so nobody can send one after another.
"""

import logging
import time
from math import ceil
from typing import TYPE_CHECKING, Any, NamedTuple

import discord
from aiohttp import web
from redbot.core.utils.chat_formatting import pagify

from .member import LEVEL_30_ROLES, _text

if TYPE_CHECKING:
    from .dashboard import Dashboard

APPLICATIONS_CHANNEL = 1418772229633605692
# ponytail: in memory, so a restart lets members apply again; store it in Config if that gets abused
COOLDOWN = 7 * 24 * 3600
SHORT_LIMIT, LONG_LIMIT = 200, 1500
EMBED_PAGE = 4000  # an embed description holds 4096 characters

log = logging.getLogger("red.kirin_cogs.dashboard.apply")


class Question(NamedTuple):
    key: str
    label: str
    long: bool = False
    required: bool = True
    hint: str = ""


class Section(NamedTuple):
    title: str
    text: str
    questions: tuple[Question, ...]


SCENARIOS = (
    "Two people are having a heated discussion even though they are still being civil to each other.",
    "One person is typing slurs against another person.",
    "A staff member has asked someone to stop doing something but they disregard the request.",
    "A staff member is disobeying the rules.",
    "Someone is harassing another member in direct messages.",
)
# The form, in order. The page, the checks and the message in Discord are all built from this.
SECTIONS = (
    Section(
        "Basic information",
        "",
        (
            Question("age", "How old are you?"),
            Question("timezone", "What is your time zone?", hint="For example UTC+1 or EST."),
            Question("country", "Where are you from? (Country)"),
        ),
    ),
    *(
        Section(
            f"Scenario {number}",
            text,
            (
                Question(f"scenario{number}_wrong", "What is wrong here?"),
                Question(f"scenario{number}_fix", "What should you do to alleviate the issue and why?", long=True),
            ),
        )
        for number, text in enumerate(SCENARIOS, 1)
    ),
    Section(
        "Other information",
        "",
        (
            Question("availability", "What times during the week are you available?"),
            Question("hours", "How many hours are you on Discord per day?"),
            Question("why", "Why are you interested in being a staff member?", long=True),
            Question(
                "qualified",
                "How do you feel qualified for this position?",
                long=True,
                hint="Include any relevant experience from other Discord servers, other social media platforms, etc.",
            ),
            Question("choose", "Why should we choose you over other applicants?", long=True),
            Question("banned", "Have you ever been banned on a Discord server before? If so, why?", long=True),
            Question("expect", "What do you expect to do in the server as Staff/Helper?", long=True),
            Question("changes", "Are there any changes you'd like to make to the server?", long=True, required=False),
            Question("about", "Tell us a bit about yourself!", long=True),
            Question("other", "Anything else you would like to add?", long=True, required=False),
        ),
    ),
)
QUESTIONS = tuple(question for section in SECTIONS for question in section.questions)


def read_answers(form: Any) -> tuple[dict[str, str], str]:
    """The answers in a sent form, and why they can't be sent ("" when they can)."""
    # Browsers send a textarea's line breaks as \r\n but count them as one character for maxlength.
    answers = {q.key: _text(form, q.key).replace("\r\n", "\n") for q in QUESTIONS}
    for q in QUESTIONS:
        if q.required and not answers[q.key]:
            return answers, f"Answer “{q.label}” too."
        if len(answers[q.key]) > (LONG_LIMIT if q.long else SHORT_LIMIT):
            return answers, f"Your answer to “{q.label}” is too long."
    return answers, ""


def application_text(member: discord.Member, answers: dict[str, str]) -> str:
    """The application as Discord markdown: who sent it, then a heading per section and every question with its answer."""
    level = max((r for r in member.roles if r.id in LEVEL_30_ROLES), key=lambda r: r.position, default=None)
    joined = discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "unknown"
    lines = [
        f"**Member:** {member.mention} (`{member.name}`, `{member.id}`)",
        f"**Level role:** {level.mention if level else 'none'}",
        f"**Joined:** {joined} · **Account created:** {discord.utils.format_dt(member.created_at, 'R')}",
    ]
    for section in SECTIONS:
        lines += ["", f"### {section.title}"]
        if section.text:
            lines.append(f"*{section.text}*")
        for q in section.questions:
            answer = answers.get(q.key) or "*No answer*"
            if q.long:
                lines.append(f"**{q.label}**")
                lines += [f"> {line}" for line in answer.splitlines() if line.strip()]
            else:
                lines.append(f"**{q.label}** {answer}")
    return "\n".join(lines)


def application_embeds(member: discord.Member, answers: dict[str, str], colour: discord.Colour) -> list[discord.Embed]:
    """The application in as many embeds as it takes, one message each; every part names the applicant."""
    pages = list(pagify(application_text(member, answers), page_length=EMBED_PAGE))
    embeds = []
    for number, page in enumerate(pages, 1):
        embed = discord.Embed(description=page, colour=colour)
        embed.set_author(name=f"{member.display_name} ({member.name})", icon_url=member.display_avatar.url)
        if len(pages) > 1:
            embed.set_footer(text=f"Part {number} of {len(pages)}")
        embeds.append(embed)
    embeds[0].title = "Staff application"
    embeds[-1].timestamp = discord.utils.utcnow()
    return embeds


class MemberApply:
    def __init__(self, cog: "Dashboard") -> None:
        self.cog = cog
        self._sent: dict[int, float] = {}  # user ID → time.monotonic() of their last application

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/apply", self.form)
        app.router.add_post("/apply", self.submit)

    def _applicant(self, request: web.Request) -> discord.Member:
        if not request["nav"]["apply"]:
            text = "You can apply for staff once you reach Level 30 (Platinum)."
            page = self.cog._message(request, 403, "Level 30+ only", text)
            raise web.HTTPForbidden(text=page.text, content_type="text/html")
        return request["member"]

    def _wait(self, user_id: int) -> float:
        """Seconds until the member may send another application; 0 or less when they may now."""
        sent = self._sent.get(user_id)
        return 0.0 if sent is None else sent + COOLDOWN - time.monotonic()

    async def form(
        self, request: web.Request, *, answers: dict[str, str] | None = None, error: str = "", status: int = 200
    ) -> web.Response:
        member = self._applicant(request)
        wait = self._wait(member.id)
        return self.cog._render(
            request,
            "member/apply.html",
            status=status,
            sections=SECTIONS,
            answers=answers or {},
            short_limit=SHORT_LIMIT,
            long_limit=LONG_LIMIT,
            sent=request.query.get("sent") == "1",
            days=ceil(wait / 86400) if wait > 0 and answers is None else 0,
            error=error,
        )

    async def submit(self, request: web.Request) -> web.StreamResponse:
        member = self._applicant(request)
        answers, error = read_answers(await request.post())
        try:
            if error:
                raise ValueError(error)
            await self._send(member, answers)
        except ValueError as e:
            # The answers go back into the form, so nothing typed is lost.
            return await self.form(request, answers=answers, error=str(e), status=400)
        raise web.HTTPSeeOther("/apply?sent=1")

    async def _send(self, member: discord.Member, answers: dict[str, str]) -> None:
        if (wait := self._wait(member.id)) > 0:
            raise ValueError(f"You sent an application recently. You can send another in {ceil(wait / 86400)} days.")
        now = time.monotonic()
        # Taken now so a double click can't send two; given back if this one isn't sent
        self._sent[member.id] = now
        try:
            await self._post(member, answers)
        except Exception:
            self._sent.pop(member.id, None)
            raise
        self._sent = {user_id: at for user_id, at in self._sent.items() if now - at < COOLDOWN}

    async def _post(self, member: discord.Member, answers: dict[str, str]) -> None:
        unavailable = ValueError("Applications can't be sent right now. Try again later.")
        channel = self.cog.bot.get_channel(APPLICATIONS_CHANNEL)
        if not isinstance(channel, discord.TextChannel):
            log.warning("The staff applications channel %s can't be found.", APPLICATIONS_CHANNEL)
            raise unavailable
        permissions = channel.permissions_for(channel.guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
            log.warning("The bot can't send embeds in the staff applications channel %s.", channel.id)
            raise unavailable
        colour = await self.cog.bot.get_embed_colour(channel)
        try:
            for embed in application_embeds(member, answers, colour):
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Posting a staff application from %s failed.", member.id)
            raise unavailable from None
