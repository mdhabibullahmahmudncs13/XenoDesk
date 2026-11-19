"""The onboarding conversation: the parsers, and the way the lines read.

No database here — the module is pure on purpose, so the wording and the parsing can
be checked without a Postgres and without Ollama.
"""

from decimal import Decimal
from types import SimpleNamespace

from xenovarients.platform.onboarding import (
    ASSISTANT_NAME,
    STEPS,
    closing,
    is_usable,
    line,
    next_step,
    parse_budget,
    parse_channels,
    reask_line,
)


def profile(**values: object) -> SimpleNamespace:
    filled = {
        "business_type": None,
        "location": None,
        "product_idea": None,
        "investment_budget": None,
        "team_size": None,
        "account_type": None,
        "experience": None,
        "sales_channels": [],
    }
    filled.update(values)
    return SimpleNamespace(**filled)


def test_the_budget_reads_the_way_people_write_it() -> None:
    assert parse_budget("50k") == Decimal(50000)
    assert parse_budget("1.5 lakh") == Decimal(150000)
    assert parse_budget("৳50,000") == Decimal(50000)
    assert parse_budget("around 30000 taka") == Decimal(30000)
    assert parse_budget("2 thousand") == Decimal(2000)


def test_a_budget_with_no_number_asks_again() -> None:
    assert parse_budget("no idea yet") is None
    assert parse_budget("whatever it takes") is None


def test_channels_are_read_from_free_text() -> None:
    assert parse_channels("fb and whatsapp") == ["Facebook", "WhatsApp"]
    assert parse_channels("Website, facebook, Website") == ["Website", "Facebook"]
    assert parse_channels("daraz") == ["Marketplace"]


def test_an_unknown_channel_is_kept_as_the_person_said_it() -> None:
    assert parse_channels("Instagram") == ["Instagram"]


def test_an_answer_with_no_question_is_not_left_dangling() -> None:
    """Every reply either greets, or reacts and then asks — never reacts and stops."""
    first = line(profile())
    assert first.startswith("Hey") and first.endswith("?")

    second = line(profile(business_type="A retail shop"), answered="business_type")
    assert "A retail shop" in second
    assert second.endswith("?")


def test_the_reply_echoes_what_was_understood() -> None:
    said = profile(business_type="A retail shop", location="Dhaka")
    reply = line(said, answered="location")
    assert "Dhaka" in reply and "got it" in reply
    assert next_step(said)[1].field == "product_idea"


def test_the_closing_line_says_back_what_it_heard() -> None:
    done = line(
        profile(
            business_type="A retail shop",
            location="Dhaka",
            product_idea="wireless earbuds",
            investment_budget=Decimal(50000),
            team_size="Just me",
            account_type="My business",
            experience="A bit here and there",
            sales_channels=["Facebook"],
        )
    )
    assert "A retail shop" in done and "Dhaka" in done and "wireless earbuds" in done


def test_a_reask_stays_on_the_question() -> None:
    assert "number" in reask_line("investment_budget")
    assert reask_line("sales_channels") != reask_line("location")


def test_every_step_acknowledges_what_was_said() -> None:
    """Each step has a line that reacts to its answer and still asks the next one."""
    answers: dict[str, object] = {
        "business_type": "A retail shop",
        "location": "Dhaka",
        "product_idea": "wireless earbuds",
        "investment_budget": Decimal(50000),
        "team_size": "Just me",
        "account_type": "My business",
        "experience": "This is my first time",
        "sales_channels": ["Facebook"],
    }
    for step in STEPS:
        reply = line(profile(**{step.field: answers[step.field]}), answered=step.field)
        assert reply and reply.endswith("?")


def test_a_greeting_is_not_taken_as_an_answer() -> None:
    """"hi" to the location question must not be stored and echoed as a city."""
    assert not is_usable("location", "hi")
    assert not is_usable("location", "hey there")
    assert not is_usable("location", "m")
    assert is_usable("location", "Dhaka")
    assert is_usable("location", "we're in Dhaka")


def test_the_first_question_does_not_open_with_and() -> None:
    assert not STEPS[0].ask.startswith("And")
    assert STEPS[1].ask == "Where will you be selling from?"


def test_the_assistant_introduces_herself_by_name_once() -> None:
    """The greeting names her; later lines do not keep repeating it."""
    assert ASSISTANT_NAME in line(profile())
    assert ASSISTANT_NAME not in closing(None)
