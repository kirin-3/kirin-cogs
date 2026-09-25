"""Truth table for who has to be asked before a roleplay action goes ahead."""

import pytest

from roleplay.consent import Decision, Outcome, Party, decide

REQUESTER = 1
OTHER = 2
BOT = 3
INVOKER_OWNER = 10
TARGET_OWNER = 20

ALLOW = Decision(Outcome.ALLOW)
BLOCKED = Decision(Outcome.BLOCKED)
REFUSED = Decision(Outcome.REFUSED)
ASK_TARGET = Decision(Outcome.ASK, ask_target=True)


def ask_owners(*owners: int, target: bool = False) -> Decision:
    return Decision(Outcome.ASK, owners=owners, ask_target=target)


# (case, invoker, target, passive, consent_required, expected)
# Unless said otherwise the requester is the invoker, as when a member uses an action
# on someone else, or asks someone else to do one to them with `ask`
CASES = [
    # plain actions
    ("active asks the target", Party(REQUESTER), Party(OTHER), False, True, ASK_TARGET),
    ("passive asks the target", Party(REQUESTER), Party(OTHER), True, True, ASK_TARGET),
    ("action without consent goes ahead", Party(REQUESTER), Party(OTHER), False, False, ALLOW),
    ("passive asks even if the action needs no consent", Party(REQUESTER), Party(OTHER), True, False, ASK_TARGET),
    # blocks, both ways
    (
        "target blocked the invoker",
        Party(REQUESTER),
        Party(OTHER, blocked=frozenset({REQUESTER})),
        False,
        True,
        BLOCKED,
    ),
    ("invoker blocked the target", Party(REQUESTER, blocked=frozenset({OTHER})), Party(OTHER), False, True, BLOCKED),
    (
        "a block beats being allowed",
        Party(REQUESTER),
        Party(OTHER, allowed=frozenset({REQUESTER}), blocked=frozenset({REQUESTER})),
        False,
        True,
        BLOCKED,
    ),
    # always consenting
    ("allowed member", Party(REQUESTER), Party(OTHER, allowed=frozenset({REQUESTER})), False, True, ALLOW),
    ("target's owner", Party(REQUESTER), Party(OTHER, owner_id=REQUESTER), False, True, ALLOW),
    ("public target, active", Party(REQUESTER), Party(OTHER, public=True), False, True, ALLOW),
    ("public target, passive", Party(REQUESTER), Party(OTHER, public=True), True, True, ASK_TARGET),
    ("servant target, passive", Party(REQUESTER), Party(OTHER, servant=True), True, True, ALLOW),
    ("servant target, active", Party(REQUESTER), Party(OTHER, servant=True), False, True, ASK_TARGET),
    # selective
    ("selective target refuses", Party(REQUESTER), Party(OTHER, selective=True), False, True, REFUSED),
    ("selective target refuses passive", Party(REQUESTER), Party(OTHER, selective=True), True, True, REFUSED),
    (
        "selective target accepts allowed members",
        Party(REQUESTER),
        Party(OTHER, selective=True, allowed=frozenset({REQUESTER})),
        False,
        True,
        ALLOW,
    ),
    (
        "selective target accepts their owner",
        Party(REQUESTER),
        Party(OTHER, selective=True, owner_id=REQUESTER),
        False,
        True,
        ALLOW,
    ),
    (
        "selective public target, active",
        Party(REQUESTER),
        Party(OTHER, selective=True, public=True),
        False,
        True,
        ALLOW,
    ),
    (
        "selective public target, passive",
        Party(REQUESTER),
        Party(OTHER, selective=True, public=True),
        True,
        True,
        REFUSED,
    ),
    (
        "selective servant target, passive",
        Party(REQUESTER),
        Party(OTHER, selective=True, servant=True),
        True,
        True,
        ALLOW,
    ),
    # nobody has to answer for themselves or for a bot
    ("action on yourself", Party(BOT, bot=True), Party(REQUESTER), False, True, ALLOW),
    ("action on yourself, selective", Party(BOT, bot=True), Party(REQUESTER, selective=True), False, True, ALLOW),
    ("action on a bot", Party(REQUESTER), Party(BOT, bot=True), False, True, ALLOW),
    ("ask a bot", Party(REQUESTER), Party(BOT, bot=True), True, True, ALLOW),
    # owners
    (
        "invoker's owner, then the target",
        Party(REQUESTER, owner_id=INVOKER_OWNER),
        Party(OTHER),
        False,
        True,
        ask_owners(INVOKER_OWNER, target=True),
    ),
    (
        "invoker's owner only, public target",
        Party(REQUESTER, owner_id=INVOKER_OWNER),
        Party(OTHER, public=True),
        False,
        True,
        ask_owners(INVOKER_OWNER),
    ),
    (
        "target's owner answers for them",
        Party(REQUESTER),
        Party(OTHER, owner_id=TARGET_OWNER),
        False,
        True,
        ask_owners(TARGET_OWNER),
    ),
    (
        "target's owner is asked even for a public target",
        Party(REQUESTER),
        Party(OTHER, owner_id=TARGET_OWNER, public=True),
        False,
        True,
        ask_owners(TARGET_OWNER),
    ),
    (
        "both owners together",
        Party(REQUESTER, owner_id=INVOKER_OWNER),
        Party(OTHER, owner_id=TARGET_OWNER),
        False,
        True,
        ask_owners(INVOKER_OWNER, TARGET_OWNER),
    ),
    (
        "a shared owner is asked once",
        Party(REQUESTER, owner_id=INVOKER_OWNER),
        Party(OTHER, owner_id=INVOKER_OWNER),
        False,
        True,
        ask_owners(INVOKER_OWNER),
    ),
    (
        "the target, as the invoker's owner, decides for themselves",
        Party(REQUESTER, owner_id=OTHER),
        Party(OTHER),
        False,
        True,
        ASK_TARGET,
    ),
    (
        "the target owning the invoker is public",
        Party(REQUESTER, owner_id=OTHER),
        Party(OTHER, public=True),
        False,
        True,
        ALLOW,
    ),
    (
        "action on yourself asks your owner",
        Party(BOT, bot=True),
        Party(REQUESTER, owner_id=TARGET_OWNER),
        False,
        True,
        ask_owners(TARGET_OWNER),
    ),
    (
        "asking a bot asks your owner",
        Party(REQUESTER, owner_id=INVOKER_OWNER),
        Party(BOT, bot=True),
        True,
        True,
        ask_owners(INVOKER_OWNER),
    ),
]


@pytest.mark.parametrize(
    ("invoker", "target", "passive", "consent_required", "expected"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_decide(invoker: Party, target: Party, passive: bool, consent_required: bool, expected: Decision) -> None:
    assert (
        decide(invoker, target, requester_id=REQUESTER, passive=passive, consent_required=consent_required) == expected
    )
