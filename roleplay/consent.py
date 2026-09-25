"""Decides whether a roleplay action can go ahead, and who has to be asked first

This only looks at IDs and settings, so it can be tested without Discord.
"""

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Party:
    """A member taking part in an action, with their roleplay settings.

    Attributes:
        id (int): The member's Discord user ID.
        bot (bool): Whether the member is a bot. Bots can't answer consent questions.
        owner_id (int | None): ID of the member's owner, if they have one on this server.
        public (bool): Consents to any action done to them.
        servant (bool): Consents to any request to do an action to someone else.
        selective (bool): Refuses members not in their allowed list.
        allowed (frozenset[int]): IDs of members they always consent to.
        blocked (frozenset[int]): IDs of members they never take part in actions with.
    """

    id: int
    bot: bool = False
    owner_id: int | None = None
    public: bool = False
    servant: bool = False
    selective: bool = False
    allowed: frozenset[int] = field(default_factory=frozenset)
    blocked: frozenset[int] = field(default_factory=frozenset)


class Outcome(Enum):
    ALLOW = "allow"
    ASK = "ask"
    BLOCKED = "blocked"
    REFUSED = "refused"


@dataclass(frozen=True)
class Decision:
    """What should happen with an action.

    Attributes:
        outcome (Outcome): Go ahead, ask first, or stop because of a block or refusal.
        owners (tuple[int, ...]): For ASK, IDs of the owners to ask, all together, first.
        ask_target (bool): For ASK, whether to ask the target once the owners agree.
    """

    outcome: Outcome
    owners: tuple[int, ...] = ()
    ask_target: bool = False


def decide(
    invoker: Party,
    target: Party,
    requester_id: int,
    passive: bool,
    consent_required: bool = True,
) -> Decision:
    """Decide whether ``invoker`` can do an action to ``target``.

    Args:
        invoker (Party): The member doing the action.
        target (Party): The member the action is done to.
        requester_id (int): ID of the member who used the command.
        passive (bool): The requester asked ``target`` to do the action to them (``ask``)
            instead of doing it themselves.
        consent_required (bool): The action asks for consent when done directly.
    """
    # make sure neither member is blocked by the other
    if invoker.id in target.blocked or target.id in invoker.blocked:
        return Decision(Outcome.BLOCKED)

    # owners don't need to ask the members they own, and members don't need to ask
    # the members who allow them
    if invoker.id == target.owner_id or invoker.id in target.allowed:
        return Decision(Outcome.ALLOW)

    # The target is never asked when they asked for this themselves (the command was
    # used without another member), or when they're a bot, since bots can't answer
    target_can_consent = target.id != requester_id and not target.bot

    # a selective target refuses everyone else, unless the interaction is active and
    # they are public use, or passive and they are a servant
    if target_can_consent and target.selective and not (target.servant if passive else target.public):
        return Decision(Outcome.REFUSED)

    # The target has to consent if they can and:
    # - The action is passive and the target is not a servant.
    # - The action is active, requires consent, and the target is not public use.
    if passive:
        target_consent_needed = target_can_consent and not target.servant
    else:
        target_consent_needed = target_can_consent and consent_required and not target.public

    # Owners are asked for the members they own. The invoker's owner isn't asked when
    # they're the target, who decides for themselves as the target
    owners: list[int] = []
    if invoker.owner_id is not None and invoker.owner_id != target.id:
        owners.append(invoker.owner_id)
    if target.owner_id is not None and target.owner_id not in owners:
        owners.append(target.owner_id)

    # The target's owner answers for the target
    ask_target = target_consent_needed and target.owner_id is None

    if not owners and not ask_target:
        return Decision(Outcome.ALLOW)
    return Decision(Outcome.ASK, owners=tuple(owners), ask_target=ask_target)
