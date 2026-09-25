"""Rule evaluation with no Discord objects: text folding, triggers, conditions, counts and selection."""

from __future__ import annotations

import logging
import math
import unicodedata
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import regex

from .types import TRIGGERS

log = logging.getLogger("red.kirin_cogs.automod")

REGEX_TIMEOUT = 0.1  # seconds; a slower pattern counts as no match
HISTORY_CAP = 100  # entries per member

INVITE_RE = regex.compile(r"(?i)(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+")
LINK_RE = regex.compile(r"(?i)https?://\S+|\bwww\.\S+|(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+")
MENTION_RE = regex.compile(r"<@[!&]?\d+>")
SPLIT_RE = regex.compile(r"\W+")

# Harshest punishment wins: (rank, duration). A mute or timeout ranks by its length.
RANKS = {"ban": 5, "mute": 4, "timeout": 3, "warn": 2, "nickname": 1}
PUNISHMENTS = frozenset(RANKS)
TRIGGER_GROUPS = {key: t.group for key, t in TRIGGERS.items()}


def fold(text: str) -> str:
    """Fancy Unicode letters (math script, full-width, ligatures) to plain ones."""
    return unicodedata.normalize("NFKC", text)


def words(texts: Iterable[str]) -> frozenset[str]:
    """Whole words of already folded texts, casefolded."""
    return frozenset(w for text in texts for w in SPLIT_RE.split(text.casefold()) if w)


@dataclass
class Event:
    """What a rule is evaluated against. Text and names are already folded."""

    kind: str  # message, edit, join or name
    member_id: int
    is_bot: bool = False
    role_ids: frozenset[int] = frozenset()
    channel_ids: frozenset[int] = frozenset()  # the channel and a thread's parent; empty for join and name
    channel_id: int = 0
    text: str = ""
    attachments: int = 0
    mentions: int = 0  # distinct users and roles
    names: tuple[str, ...] = ()
    at: float = 0.0
    words: frozenset[str] = field(init=False)
    name_words: frozenset[str] = field(init=False)
    links: int = field(init=False)
    mention_tokens: int = field(init=False)

    def __post_init__(self) -> None:
        self.words = words([self.text])
        self.name_words = words(self.names)
        self.links = len(LINK_RE.findall(self.text))
        self.mention_tokens = len(MENTION_RE.findall(self.text))

    @property
    def is_message(self) -> bool:
        return self.kind in ("message", "edit")


@dataclass(frozen=True)
class Entry:
    """One new message in a member's history, for counted triggers."""

    at: float
    channel_id: int
    channel_ids: frozenset[int]  # with a thread's parent, for channel conditions
    text: str
    attachments: int
    links: int
    mentions: int
    mention_tokens: int


@dataclass(frozen=True)
class Trigger:
    row: dict
    pattern: Any = None  # compiled regex
    words: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Rule:
    id: int
    name: str
    ruleset: str
    triggers: tuple[Trigger, ...]
    conditions: tuple[dict, ...]  # the ruleset's, then the rule's
    effects: tuple[dict, ...]
    rank: tuple[int, float]


@dataclass(frozen=True)
class Snapshot:
    rules: tuple[Rule, ...] = ()
    window: int = 0  # longest counted-trigger window, seconds


EMPTY = Snapshot()


def rank(effects: Iterable[dict]) -> tuple[int, float]:
    best = (0, 0.0)
    for effect in effects:
        if effect["type"] not in RANKS:
            continue
        minutes = effect.get("minutes", 0)
        duration = math.inf if effect["type"] == "mute" and minutes == 0 else float(minutes)
        best = max(best, (RANKS[effect["type"]], duration))
    return best


def compile_document(document: dict) -> Snapshot:
    """Build the snapshot events read from. `document` must already be validated."""
    lists = {item["id"]: frozenset(words(fold(w) for w in item["words"])) for item in document["lists"]}
    rules, window = [], 0
    for ruleset in document["rulesets"]:
        if not ruleset["enabled"]:
            continue
        for rule in ruleset["rules"]:
            triggers = []
            for row in rule["triggers"]:
                if "seconds" in row:
                    window = max(window, row["seconds"])
                triggers.append(
                    Trigger(
                        row,
                        regex.compile(row["pattern"]) if "pattern" in row else None,
                        lists.get(row.get("list", 0), frozenset()),
                    )
                )
            rules.append(
                Rule(
                    rule["id"],
                    rule["name"],
                    ruleset["name"],
                    tuple(triggers),
                    (*ruleset["conditions"], *rule["conditions"]),
                    tuple(rule["effects"]),
                    rank(rule["effects"]),
                )
            )
    return Snapshot(tuple(rules), window)


def _search(pattern: Any, texts: Iterable[str], rule: Rule) -> bool:
    try:
        return any(pattern.search(text, timeout=REGEX_TIMEOUT) for text in texts)
    except TimeoutError:
        log.warning("Automod regex timed out in %s / %s", rule.ruleset, rule.name)
        return False


def _channel_allowed(channel_ids: frozenset[int], conditions: tuple[dict, ...]) -> bool:
    """Whether a message in these channels passes the rule's channel conditions."""
    for c in conditions:
        if c["type"] == "ignore_channels" and channel_ids.intersection(c["channels"]):
            return False
        if c["type"] == "only_channels" and not channel_ids.intersection(c["channels"]):
            return False
    return True


def _counted(row: dict, event: Event, history: deque[Entry], rule: Rule) -> bool:
    # Messages in channels the rule ignores (bot-spam, games) don't add to its counts.
    since = event.at - row["seconds"]
    recent = [e for e in history if e.at >= since and _channel_allowed(e.channel_ids, rule.conditions)]
    kind, count = row["type"], row["count"]
    if kind == "message_rate":
        return len(recent) >= count
    if kind == "duplicates":
        if not event.text.strip():
            return False
        pool = recent if row["any_channel"] else [e for e in recent if e.channel_id == event.channel_id]
        last = pool[-count:]
        return len(last) == count and all(e.text == event.text for e in last)
    if kind == "attachment_rate":
        return sum(e.attachments if row["per_attachment"] else min(e.attachments, 1) for e in recent) >= count
    if kind == "link_rate":
        return sum(e.links for e in recent) >= count
    if kind == "mention_rate":
        return sum(e.mention_tokens if row["repeats"] else e.mentions for e in recent) >= count
    return False


def trigger_matches(trigger: Trigger, event: Event, history: deque[Entry], rule: Rule) -> bool:
    row = trigger.row
    kind = row["type"]
    group = TRIGGER_GROUPS[kind]
    if group == "name":
        if event.kind not in ("join", "name"):
            return False
        if kind == "name_regex":
            return _search(trigger.pattern, event.names, rule)
        return bool(trigger.words & event.name_words)
    if not event.is_message:
        return False
    if group == "counted":
        return event.kind == "message" and _counted(row, event, history, rule)
    if kind == "regex":
        return _search(trigger.pattern, [event.text], rule)
    if kind == "not_regex":
        try:
            return trigger.pattern.search(event.text, timeout=REGEX_TIMEOUT) is None
        except TimeoutError:
            log.warning("Automod regex timed out in %s / %s", rule.ruleset, rule.name)
            return False
    if kind == "words":
        return bool(trigger.words & event.words)
    if kind == "invite":
        return INVITE_RE.search(event.text) is not None
    if kind == "link":
        return event.links > 0
    if kind == "mentions":
        return event.mentions >= row["count"]
    return False


def condition_holds(row: dict, event: Event, role_exists: Callable[[int], bool]) -> bool:
    kind = row["type"]
    if kind == "ignore_bots":
        return not event.is_bot
    if kind == "ignore_roles":
        return not event.role_ids.intersection(row["roles"])
    if kind == "require_roles":
        if row["all"]:
            return all(r in event.role_ids for r in row["roles"] if role_exists(r))
        return bool(event.role_ids.intersection(row["roles"]))
    if kind == "ignore_channels":
        return not event.channel_ids.intersection(row["channels"])
    if kind == "only_channels":
        return bool(event.channel_ids.intersection(row["channels"]))
    if kind == "new_only":
        return event.kind == "message"
    if kind == "edits_only":
        return event.kind == "edit"
    return False


@dataclass
class Hit:
    rule: Rule
    trigger: dict


def evaluate(
    snapshot: Snapshot, event: Event, history: deque[Entry], role_exists: Callable[[int], bool] = lambda _: True
) -> list[Hit]:
    """Every rule that fires, in order, with the first trigger that matched."""
    hits = []
    for rule in snapshot.rules:
        if not all(condition_holds(c, event, role_exists) for c in rule.conditions):
            continue
        trigger = next((t for t in rule.triggers if trigger_matches(t, event, history, rule)), None)
        if trigger is not None:
            hits.append(Hit(rule, trigger.row))
    return hits


def plan(hits: list[Hit], event: Event) -> list[tuple[Rule, dict]]:
    """The actions to take: one delete, the harshest rule's punishments, and every send."""
    if not hits:
        return []
    steps: list[tuple[Rule, dict]] = []
    if event.is_message:
        deleter = next((h.rule for h in hits if any(e["type"] == "delete" for e in h.rule.effects)), None)
        if deleter is not None:
            steps.append((deleter, {"type": "delete"}))
    winner = max(hits, key=lambda h: h.rule.rank).rule  # max keeps the first of equal ranks
    steps += [(winner, e) for e in winner.effects if e["type"] in PUNISHMENTS]
    steps += [(h.rule, e) for h in hits for e in h.rule.effects if e["type"] == "send"]
    return steps


def is_counted(trigger: dict) -> bool:
    return TRIGGER_GROUPS.get(trigger["type"]) == "counted"


class Counts:
    """Per-member history of new messages for counted triggers. In memory only."""

    def __init__(self) -> None:
        self.members: dict[int, deque[Entry]] = {}

    def add(self, event: Event, window: int) -> deque[Entry]:
        if event.kind != "message" or window <= 0:
            return self.members.get(event.member_id, deque())
        history = self.members.setdefault(event.member_id, deque(maxlen=HISTORY_CAP))
        while history and history[0].at < event.at - window:
            history.popleft()
        history.append(
            Entry(
                event.at,
                event.channel_id,
                event.channel_ids,
                event.text,
                event.attachments,
                event.links,
                event.mentions,
                event.mention_tokens,
            )
        )
        return history

    def reset(self, member_id: int) -> None:
        self.members.pop(member_id, None)

    def sweep(self, now: float, window: int) -> None:
        """Drop members with nothing inside the window."""
        for member_id in [m for m, h in self.members.items() if not h or h[-1].at < now - window]:
            del self.members[member_id]
