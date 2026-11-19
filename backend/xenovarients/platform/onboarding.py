"""The onboarding conversation, as words rather than a form.

The questions here are written the way a person asks them, and every reply opens by
reacting to what the person just said ("Retail — nice.") before asking the next thing.
That reaction is the difference between a chat and an interview: a form never
acknowledges an answer, and a person always does.

**The script owns the questions and the option buttons; the model only rewords.** The
answer parser reads a fixed set of fields, so a model that invents a question or an
unrecognised option would break the conversation it is meant to smooth. The API layer
asks the model for a natural rephrasing and falls back to these lines.

Nothing in this module touches the database, so the wording and the parsers are
testable without one.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Who the person is talking to. One name on every line, so the chat reads as one
# assistant rather than a series of system prompts.
ASSISTANT_NAME = "Xeni"

# The hard limit the profile columns impose, so a chatty answer is trimmed instead of
# failing the write with a database error.
MAX_LENGTHS: dict[str, int] = {
    "business_type": 64,
    "location": 128,
    "product_idea": 255,
    "team_size": 32,
    "account_type": 32,
    "experience": 32,
}


@dataclass(frozen=True)
class Step:
    """One question, and the quick replies that answer it in the person's own voice."""

    field: str
    ask: str
    options: tuple[str, ...] = ()


STEPS: tuple[Step, ...] = (
    Step(
        "business_type",
        "What kind of business are you running right now?",
        ("A retail shop", "An online store", "Wholesale", "Manufacturing"),
    ),
    Step(
        "location",
        "Where will you be selling from?",
        ("Bangladesh", "Dhaka", "Online only", "Other"),
    ),
    Step("product_idea", "What product are you thinking of sourcing first?"),
    Step("investment_budget", "Roughly how much are you planning to put in, in taka?"),
    Step(
        "team_size",
        "Is it just you doing this, or is there a team?",
        ("Just me", "2–5 of us", "6–20", "More than 20"),
    ),
    Step(
        "account_type",
        "Are you setting this up as yourself, or as a registered business?",
        ("Myself", "My business"),
    ),
    Step(
        "experience",
        "How much sourcing have you done before?",
        ("This is my first time", "A bit here and there", "I've done this a lot"),
    ),
    Step(
        "sales_channels",
        "Last one — where do your customers find you today? Pick as many as apply.",
        ("Website", "Facebook", "WhatsApp", "Marketplace"),
    ),
)

GREETING = (
    f"Hey, I'm {ASSISTANT_NAME} — I'll get your workspace set up so it fits your business. "
    "A few quick questions, about a minute. What kind of business are you running right now?"
)

# How a person acknowledges each kind of answer. Short on purpose: a real
# acknowledgment is a beat, not a paragraph.
_ACKNOWLEDGEMENTS: dict[str, str] = {
    "business_type": "{value} — nice.",
    "location": "{value}, got it.",
    "product_idea": "{value} — good one to start with.",
    "investment_budget": "{value} taka to work with, noted.",
    "team_size": "{value} — makes sense.",
    "account_type": "{value} — understood.",
    "experience": "{value} — that's fine.",
    "sales_channels": "Okay — {value}.",
}

_REASKS: dict[str, str] = {
    "location": (
        "Sorry — could you tell me the city or country you'll be selling from?"
    ),
    "investment_budget": (
        "Sorry, I didn't catch a number there — roughly how many taka are you "
        "thinking of putting in?"
    ),
    "sales_channels": (
        "I didn't catch a channel in that — pick one below, or just tell me where "
        "people reach you."
    ),
}
_DEFAULT_REASK = "Sorry, I didn't quite get that — could you say it again?"

# Words that are politeness rather than an answer. "hi" as a city is not a thing, and
# echoing it back ("hi, got it.") is how a chat stops sounding like a person.
_GREETINGS: frozenset[str] = frozenset(
    {
        "hi",
        "hii",
        "hiya",
        "hey",
        "heyy",
        "hello",
        "yo",
        "sup",
        "howdy",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "cool",
        "nice",
        "test",
        "hmm",
        "idk",
    }
)


def is_usable(field: str, text: str) -> bool:
    """Whether ``text`` answers the question instead of being a stray word or greeting.

    Deliberately light: a real person says "we're in Dhaka" and that must be taken as
    written. Only a bare greeting ("hi", "hey there") or a single character is
    rejected, so the assistant can ask again instead of recording nonsense.
    """
    cleaned = " ".join(text.split()).strip(" .,!?-")
    if len(cleaned) < 2:
        return False
    words = cleaned.lower().split()
    return not (len(words) <= 2 and words[0] in _GREETINGS)


def next_step(profile: Any) -> tuple[int, Step | None]:
    """The first unanswered step, or ``(len(STEPS), None)`` when everything is filled."""
    if profile is None:
        return 0, STEPS[0]
    for index, step in enumerate(STEPS):
        value = getattr(profile, step.field, None)
        if isinstance(value, list):
            if not value:
                return index, step
        elif value is None or value == "":
            return index, step
    return len(STEPS), None


def line(profile: Any, answered: str | None = None) -> str:
    """The assistant's next line: greet, acknowledge-then-ask, or close.

    ``answered`` is the field just filled, so the reply can react to it. Without it —
    returning to a half-finished profile — the question is asked plainly rather than
    pretending to remember something it was not told in this conversation.
    """
    index, step = next_step(profile)
    if step is None:
        return closing(profile)
    if answered is None:
        return GREETING if index == 0 else step.ask
    return f"{_acknowledge(answered, profile)} {step.ask}".strip()


def reask_line(field: str) -> str:
    """What to say when an answer could not be used — stay on the question, kindly."""
    return _REASKS.get(field, _DEFAULT_REASK)


def closing(profile: Any) -> str:
    """The last line: what was understood, said back, plus the next place to go."""
    if profile is None:
        return (
            "That's everything I needed. Open Market Intelligence whenever you're ready "
            "and I'll work from this."
        )
    parts: list[str] = []
    if getattr(profile, "business_type", None):
        parts.append(profile.business_type)
    if getattr(profile, "location", None):
        parts.append(f"in {profile.location}")
    summary = " ".join(parts)
    if getattr(profile, "product_idea", None):
        summary = f"{summary}, sourcing {profile.product_idea}" if summary else (
            f"sourcing {profile.product_idea}"
        )
    understood = f"All set — {summary}." if summary else "All set."
    return (
        f"{understood} I've saved all of it. Open Market Intelligence whenever you're "
        "ready and I'll work from this."
    )


def _acknowledge(field: str, profile: Any) -> str:
    """A short, human reaction to the answer just given."""
    value = getattr(profile, field, None)
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    if not value:
        return ""
    value = str(value)
    if field == "investment_budget":
        value = f"{Decimal(value):,.0f}"
    elif value[:1].islower():
        # "dhaka" reads as "Dhaka" when the assistant says it back.
        value = value[:1].upper() + value[1:]
    return _ACKNOWLEDGEMENTS.get(field, "{value}.").format(value=value)


# Multipliers people type instead of digits. Longest first so "million" is not read
# as "m", and "lakh" before "k".
_MULTIPLIERS: tuple[tuple[str, int], ...] = (
    ("million", 1_000_000),
    ("lakh", 100_000),
    ("lac", 100_000),
    ("thousand", 1_000),
    ("k", 1_000),
)


def parse_budget(text: str) -> Decimal | None:
    """Read a budget the way a person writes one: "50k", "1.5 lakh", "৳50,000".

    Returns ``None`` when there is no number at all, so the caller can ask again
    instead of guessing.
    """
    cleaned = text.lower().replace(",", "").replace("৳", " ")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if match is None:
        return None
    amount = float(match.group())
    tail = cleaned[match.end():].strip()
    for word, factor in _MULTIPLIERS:
        if tail.startswith(word):
            amount *= factor
            break
    return Decimal(int(round(amount)))


# The four channels the product supports, plus the ways people actually name them.
_CHANNEL_ALIASES: dict[str, str] = {
    "web": "Website",
    "website": "Website",
    "site": "Website",
    "own site": "Website",
    "fb": "Facebook",
    "facebook": "Facebook",
    "facebook page": "Facebook",
    "meta": "Facebook",
    "wa": "WhatsApp",
    "whatsapp": "WhatsApp",
    "whats app": "WhatsApp",
    "marketplace": "Marketplace",
    "daraz": "Marketplace",
}

_CHANNEL_SPLIT = re.compile(r",|/|&|\band\b|\+")


def parse_channels(text: str) -> list[str]:
    """Read sales channels from free text, keeping the order and dropping repeats.

    A name outside the known four is kept as the person typed it — telling someone
    their shop is not a real channel is worse than storing one unrecognised value.
    """
    found: list[str] = []
    for part in _CHANNEL_SPLIT.split(text):
        raw = part.strip().strip(".")
        if not raw:
            continue
        key = raw.lower()
        name = _CHANNEL_ALIASES.get(key) or _CHANNEL_ALIASES.get(key.split()[0])
        if name is None:
            name = raw[:40].title()
        if name.lower() not in {item.lower() for item in found}:
            found.append(name)
    return found
