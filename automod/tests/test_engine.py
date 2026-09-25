from collections import deque

from automod.engine import Counts, Event, compile_document, evaluate, fold, plan
from automod.tests.helpers import document, rule, ruleset, word_list
from automod.types import validate

LOW, GOLD, STAFF = 1, 2, 3
INVITE = {"type": "invite"}


def snap(*rulesets, lists=None):
    return compile_document(validate(document(*rulesets, lists=lists)))


def msg(text: str = "", **kw) -> Event:
    return Event("message", 7, text=fold(text), channel_ids=frozenset({10}), channel_id=10, **kw)


def fires(snapshot, event, history=None) -> list[str]:
    return [h.rule.name for h in evaluate(snapshot, event, history if history is not None else deque())]


def test_word_lists_match_whole_words_and_fancy_letters() -> None:
    s = snap(
        ruleset("words", [rule("r", [{"type": "words", "list": 900}])]),
        lists=[word_list("w", ["badword", "ass"], 900)],
    )
    assert fires(s, msg("that is BADWORD!")) == ["r"]
    assert fires(s, msg("first class")) == []
    bold = "".join(chr(0x1D41A + ord(c) - ord("a")) for c in "badword")  # mathematical bold letters
    assert fires(s, msg(f"you {bold}")) == ["r"]
    full_width = "".join(chr(0xFF41 + ord(c) - ord("a")) for c in "badword")
    assert fires(s, msg(full_width)) == ["r"]


def test_regex_no_match_links_and_invites() -> None:
    s = snap(
        ruleset("a", [rule("no-at", [{"type": "not_regex", "pattern": "@"}])]),
        ruleset("b", [rule("invite", [INVITE]), rule("link", [{"type": "link"}])]),
    )
    assert fires(s, msg("hello")) == ["no-at"]
    assert fires(s, msg("@someone hi")) == []
    assert fires(s, msg("@x join discord.gg/abc123")) == ["invite", "link"]
    assert fires(s, msg("@x see example.com")) == []
    assert fires(s, msg("@x www.example.com")) == ["link"]


def test_distinct_mentions_threshold() -> None:
    s = snap(ruleset("s", [rule("ping", [{"type": "mentions", "count": 6}])]))
    assert fires(s, msg("<@1> " * 7, mentions=1)) == []
    assert fires(s, msg("hi", mentions=6)) == ["ping"]


def test_timed_out_pattern_counts_as_no_match() -> None:
    slow = "(x+x+)+y"
    s = snap(
        ruleset(
            "s", [rule("r", [{"type": "regex", "pattern": slow}]), rule("n", [{"type": "not_regex", "pattern": slow}])]
        )
    )
    assert fires(s, msg("x" * 5000)) == []


def _burst(s, texts, channels=None, attachments=None):
    counts, result = Counts(), []
    for n, text in enumerate(texts):
        event = Event(
            "message",
            7,
            text=text,
            channel_id=(channels or [10] * len(texts))[n],
            attachments=(attachments or [0] * len(texts))[n],
            at=100.0 + n * 0.5,
        )
        hits = evaluate(s, event, counts.add(event, s.window))
        if hits:
            counts.reset(7)
        result.append(bool(hits))
    return result


def test_burst_fires_once() -> None:
    s = snap(ruleset("spam", [rule("r", [{"type": "message_rate", "count": 5, "seconds": 5}])]))
    assert _burst(s, list("abcdef")) == [False, False, False, False, True, False]


def test_identical_messages_per_channel_unless_any_channel() -> None:
    same = {"type": "duplicates", "count": 4, "seconds": 25}
    per_channel = snap(ruleset("s", [rule("r", [same])]))
    anywhere = snap(ruleset("s", [rule("r", [{**same, "any_channel": True}])]))
    channels = [1, 1, 2, 2]
    assert _burst(per_channel, ["hi"] * 4, channels) == [False] * 4
    assert _burst(anywhere, ["hi"] * 4, channels)[-1] is True
    assert _burst(per_channel, ["hi", "hi", "yo", "hi"]) == [False] * 4


def test_attachment_counting_options() -> None:
    once = {"type": "attachment_rate", "count": 3, "seconds": 30}
    assert _burst(snap(ruleset("s", [rule("r", [once])])), ["", ""], attachments=[3, 1]) == [False, False]
    every = snap(ruleset("s", [rule("r", [{**once, "per_attachment": True}])]))
    assert _burst(every, ["", ""], attachments=[3, 1]) == [True, False]


def test_conditions_threads_names_and_deleted_roles() -> None:
    link = {"type": "link"}
    s = snap(ruleset("comfy", [rule("r", [link], conditions=[{"type": "only_channels", "channels": [10]}])]))
    in_thread = Event("message", 7, text="https://x.y", channel_ids=frozenset({55, 10}), channel_id=55)
    assert fires(s, in_thread) == ["r"]

    name = snap(
        ruleset(
            "n",
            [
                rule(
                    "r",
                    [{"type": "name_regex", "pattern": "(?i)kirin"}],
                    conditions=[{"type": "only_channels", "channels": [10]}],
                )
            ],
        )
    )
    assert fires(name, Event("name", 7, names=("KiRiN",))) == []

    need_all = snap(
        ruleset("s", [rule("r", [link], conditions=[{"type": "require_roles", "roles": [LOW, 999], "all": True}])])
    )
    event = msg("https://x.y", role_ids=frozenset({LOW}))
    assert evaluate(need_all, event, deque(), role_exists=lambda r: r != 999)  # role 999 was deleted
    assert not evaluate(need_all, event, deque())


def test_ruleset_conditions_and_disabled_rulesets() -> None:
    s = snap(
        ruleset("a", [rule("staff", [INVITE])], conditions=[{"type": "ignore_roles", "roles": [STAFF]}]),
        ruleset("b", [rule("off", [INVITE])], enabled=False),
    )
    assert fires(s, msg("discord.gg/x", role_ids=frozenset({STAFF}))) == []
    assert fires(s, msg("discord.gg/x")) == ["staff"]


def test_name_word_list_on_display_name() -> None:
    s = snap(ruleset("n", [rule("r", [{"type": "name_words", "list": 900}])]), lists=[word_list("w", ["slur"], 900)])
    assert fires(s, Event("name", 7, names=("nice nick", "a SLUR here", "user"))) == ["r"]
    assert fires(s, msg("slur")) == []  # name triggers only look at names


def _plan(s, event):
    return [(r.name, e["type"]) for r, e in plan(evaluate(s, event, deque()), event)]


def test_harshest_rule_wins() -> None:
    delete = {"type": "delete"}
    s = snap(
        ruleset(
            "invite",
            [
                rule("invite", [INVITE], [delete, {"type": "warn"}, {"type": "mute", "minutes": 1440}]),
                rule(
                    "blacklisted",
                    [{"type": "regex", "pattern": "discord.gg/family"}],
                    [
                        delete,
                        {"type": "mute", "minutes": 0},
                        {"type": "send", "text": "Spam", "channel": 5},
                    ],
                ),
                rule(
                    "ban bots",
                    [INVITE],
                    [{"type": "ban", "delete_days": 1}],
                    conditions=[{"type": "require_roles", "roles": [LOW]}],
                ),
            ],
        )
    )
    assert _plan(s, msg("discord.gg/abc", role_ids=frozenset({LOW}))) == [("invite", "delete"), ("ban bots", "ban")]
    assert _plan(s, msg("discord.gg/family", role_ids=frozenset({GOLD}))) == [
        ("invite", "delete"),
        ("blacklisted", "mute"),
        ("blacklisted", "send"),
    ]


def test_ties_go_to_the_first_rule_and_names_skip_deletes() -> None:
    mute = [{"type": "delete"}, {"type": "mute", "minutes": 60}]
    s = snap(ruleset("s", [rule("first", [INVITE], mute), rule("second", [INVITE], mute)]))
    assert _plan(s, msg("discord.gg/x")) == [("first", "delete"), ("first", "mute")]
    n = snap(ruleset("n", [rule("r", [{"type": "name_regex", "pattern": "x"}], [{"type": "delete"}])]))
    assert _plan(n, Event("join", 7, names=("x",))) == []


def test_idle_members_are_swept() -> None:
    counts = Counts()
    counts.add(Event("message", 1, at=100.0), window=10)
    counts.add(Event("message", 2, at=150.0), window=10)
    counts.sweep(now=155.0, window=10)
    assert list(counts.members) == [2]


def test_counted_triggers_skip_channels_the_rule_ignores() -> None:
    burst = {"type": "message_rate", "count": 3, "seconds": 10}
    s = snap(ruleset("spam", [rule("r", [burst])], conditions=[{"type": "ignore_channels", "channels": [99]}]))
    counts = Counts()
    fired = []
    for n, channel in enumerate([99, 99, 10, 10, 10]):  # two game commands, then three messages in #general
        event = Event("message", 7, channel_ids=frozenset({channel}), channel_id=channel, at=100.0 + n)
        fired.append(bool(evaluate(s, event, counts.add(event, s.window))))
    assert fired == [False, False, False, False, True]
