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
# Discord allows 4000 characters of text across one Components V2 message; this leaves room for the "part 2 of 3" line.
TEXT_LIMIT = 3950
BLOCK_LIMIT = 3000  # a longer question-and-answer is split at a line break, so a block always fits a message
ACCENT = 0xDCCBFF  # the site's lavender

log = logging.getLogger("red.kirin_cogs.dashboard.apply")


class Question(NamedTuple):
    key: str
    label: str
    long: bool = False
    required: bool = True
    hint: str = ""
    digits: int = 0  # when set, the answer must be a number with exactly this many digits


class Section(NamedTuple):
    title: str
    emoji: str
    tone: str  # the pastel of its card on the page (a tone-* class in style.css)
    text: str
    questions: tuple[Question, ...]
    items: tuple[str, ...] = ()  # a numbered list under the text, for questions that point at it


# Grey areas from the rules (2.3/2.5, 3.1, 1.2/1.3, 8.5a, 6.6, 3.7/9.1, 6.7); the applicant talks through two.
SITUATIONS = (
    "Two regulars roast each other all the time. A newer member joins in with the same kind of jokes aimed at one of "
    "them, and that person goes quiet.",
    "A member reports DMs from someone who ignored their DO NOT DM role. The other person says the two of them had "
    "been chatting before.",
    'Someone keeps making "jokes" that make you wonder if they\'re actually underage.',
    "An image is posted that might fall under rule 8.5, but you're honestly not sure.",
    "A friend of yours breaks a rule, and other members are watching how you handle it.",
    "A post in the vent channel makes you worry the person might hurt themselves.",
    "Another staff member makes a call in chat that you think is wrong.",
)
PICK_HINT = "Start with the situation's number."
# The form, in order. The page, the checks and the message in Discord are all built from this.
SECTIONS = (
    Section(
        "About you",
        "🌸",
        "pink",
        "The easy part, so we know who we're talking to.",
        (
            Question("name", "What should we call you, and what are your pronouns?", hint="Pronouns are optional."),
            Question("age", "How old are you?", digits=2),
            Question("around", "What's your time zone, and when are you usually around?"),
            Question("time", "How much time could you realistically give us in a week?"),
            Question("unicornia", "What do you like about Unicornia, and what's one thing you'd change?", long=True),
        ),
    ),
    Section(
        "How you'd handle things",
        "💭",
        "sky",
        "There's no right answer. We want to see how you think: what you'd want to know first, what you'd do, and "
        "what you'd say. Pick two of these situations and talk us through them.",
        (
            Question("pick1", "Your first pick", long=True, hint=PICK_HINT),
            Question("pick2", "Your second pick", long=True, hint=PICK_HINT),
            Question(
                "conflict",
                "Tell us about a time you dealt with a conflict, on Discord or anywhere else. What happened, and what "
                "would you do differently now?",
                long=True,
            ),
            Question(
                "hand_off",
                "When would you hand something to senior staff or Kirin rather than deal with it yourself?",
                long=True,
            ),
        ),
        SITUATIONS,
    ),
    Section(
        "Being honest",
        "🫶",
        "mint",
        "Nobody's perfect, and that's fine. Honest answers help us much more than polished ones.",
        (
            Question(
                "experience",
                "Have you been staff anywhere before? What did you do there, and why did you stop?",
                long=True,
            ),
            Question(
                "history",
                "Have you ever been warned, muted or banned, here or elsewhere? What happened?",
                long=True,
                hint="We care more about what you took from it than whether it happened.",
            ),
            Question(
                "boundaries",
                "Staff here sometimes see explicit or upsetting things: reports, vents, ban evidence. Is there anything "
                "you'd rather not have to deal with?",
                long=True,
                required=False,
                hint="This won't count against you.",
            ),
            Question("hardest", "What do you think you'd find hardest about being staff?", long=True),
        ),
    ),
    Section(
        "Last bit",
        "✨",
        "butter",
        "Almost done!",
        (
            Question("why", "Why do you want to do this?", long=True, hint="Honest answers welcome."),
            Question("other", "Anything else you want us to know?", long=True, required=False),
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
        answer = answers[q.key]
        # isascii: isdigit alone also takes "²" and other scripts' digits
        if q.digits and answer and not (answer.isascii() and answer.isdigit() and len(answer) == q.digits):
            return answers, f"Answer “{q.label}” with a {q.digits}-digit number."
    return answers, ""


def _answer(question: Question, answer: str) -> str:
    """The question in small grey text over the answer, like a form response. The answer's markdown is escaped, so a
    stray heading, code block or subtext line in it can't restyle the rest of the message."""
    lines = [discord.utils.escape_markdown(line.strip()) for line in answer.splitlines() if line.strip()]
    return f"-# {question.label}\n" + ("\n".join(lines) or "*No answer*")


def _blocks(section: Section, answers: dict[str, str]) -> list[str]:
    """The section's heading, then each question with its answer, in pieces that each fit a message. The heading and
    numbered list go with the first question, so they're never left at the bottom of one message."""
    intro = [f"### {section.emoji} {section.title}"]
    intro += [f"-# **{number}.** {item}" for number, item in enumerate(section.items, 1)]
    blocks = [_answer(q, answers.get(q.key, "")) for q in section.questions]
    blocks[0] = "\n".join(intro) + ("\n\n" if section.items else "\n") + blocks[0]
    # pagify only splits a block too long for a message on its own, at a line break
    return [piece for block in blocks for piece in pagify(block, page_length=BLOCK_LIMIT)]


def _header(member: discord.Member) -> tuple[str, str]:
    """The title and details next to the applicant's avatar."""
    level = max((r for r in member.roles if r.id in LEVEL_30_ROLES), key=lambda r: r.position, default=None)

    def when(moment: Any) -> str:
        if moment is None:
            return "unknown"
        return f"{discord.utils.format_dt(moment, 'D')} · {discord.utils.format_dt(moment, 'R')}"

    details = (
        f"{member.mention} · `{member.name}` · `{member.id}`\n"
        f"**Level** {level.mention if level else 'none'}\n"
        f"**Joined** {when(member.joined_at)}\n"
        f"**Account created** {when(member.created_at)}"
    )
    return "## 📝 New staff application", details


def _continued(member: discord.Member) -> str:
    return f"-# {member.mention}'s staff application, continued"


def application_messages(member: discord.Member, answers: dict[str, str]) -> list[discord.ui.LayoutView]:
    """The application as Components V2 messages: one lavender card each, with the applicant's avatar and details at
    the top and a divider between sections. Answers are packed in order into as few messages as Discord's text limit
    allows; one is only split if it's too long for a message on its own. Each message after the first names the
    applicant, and each is numbered when there are several."""
    pages: list[list[str]] = [[]]  # each message's section texts
    used = sum(map(len, _header(member)))
    for section in SECTIONS:
        for number, block in enumerate(_blocks(section, answers)):
            if number and used + 2 + len(block) <= TEXT_LIMIT:
                pages[-1][-1] += f"\n\n{block}"
                used += 2 + len(block)
                continue
            if number:  # the section goes on in the next message
                block = f"### {section.emoji} {section.title} (continued)\n{block}"
            if used + len(block) > TEXT_LIMIT:
                pages.append([])
                used = len(_continued(member))
            pages[-1].append(block)
            used += len(block)
    return [_card(member, texts, number, len(pages)) for number, texts in enumerate(pages, 1)]


def _card(member: discord.Member, texts: list[str], number: int, parts: int) -> discord.ui.LayoutView:
    card = discord.ui.Container(accent_colour=ACCENT)
    if number == 1:
        card.add_item(discord.ui.Section(*_header(member), accessory=discord.ui.Thumbnail(member.display_avatar.url)))
    else:
        card.add_item(discord.ui.TextDisplay(_continued(member)))
    for text in texts:
        card.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        card.add_item(discord.ui.TextDisplay(text))
    if parts > 1:
        card.add_item(discord.ui.TextDisplay(f"-# part {number} of {parts}"))
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(card)
    return view


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
            member=member,
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
        try:
            for view in application_messages(member, answers):
                await channel.send(view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Posting a staff application from %s failed.", member.id)
            raise unavailable from None
