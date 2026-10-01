"""The model-named image subject, and the keyword table it falls back on.

Every case here is mocked. The call itself is cheap, but a test suite that
spends money on every run is one nobody runs.
"""

from unittest.mock import patch

import pytest

from image_generator import ImageGenerator
from langchain_blog_agent import IMAGE_SUBJECT_SOURCE_CHARS, describe_image_subject


class FakeChain:
    """Stands in for prompt | llm | parser."""

    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.seen = None

    def invoke(self, values):
        self.seen = values
        if self.error:
            raise self.error
        return self.answer


def run_with(answer=None, error=None, title="Mars debuts Cheez-It Protein",
             content="", look="Studio product hero."):
    chain = FakeChain(answer, error)
    with patch("langchain_blog_agent.create_openai_chat_model"), patch(
        "langchain_blog_agent.ChatPromptTemplate"
    ) as prompt:
        prompt.from_messages.return_value.__or__ = lambda *_: chain
        # prompt | llm | parser collapses to the fake chain
        with patch.object(type(chain), "__or__", lambda self, _other: self, create=True):
            return describe_image_subject(title, content, look=look), chain


def test_a_good_answer_becomes_the_subject():
    subject, _ = run_with("stacked square crackers spilling from a generic box")

    assert subject == "stacked square crackers spilling from a generic box"


@pytest.mark.parametrize(
    "answer,why",
    [
        ("", "empty"),
        ("   ", "whitespace"),
        (None, "nothing returned"),
        ("I'm sorry, I cannot help with that request", "a refusal"),
        ("As an AI model I would suggest a photograph of groceries", "a refusal"),
        ("x" * 400, "too long to be a brief"),
    ],
)
def test_an_unusable_answer_falls_back_to_the_table(answer, why):
    subject, _ = run_with(answer)

    assert subject is None, why


def test_a_failed_call_never_raises():
    """An image subject is not worth failing a generation run over."""
    subject, _ = run_with(error=RuntimeError("502 from the provider"))

    assert subject is None


def test_the_answer_is_tidied():
    subject, _ = run_with('  "a bag of loose spinach leaves."  ')

    assert subject == "a bag of loose spinach leaves"


def test_an_empty_title_costs_nothing():
    """No headline, no call: the cheapest request is the one not sent."""
    with patch("langchain_blog_agent.create_openai_chat_model") as model:
        assert describe_image_subject("", "some body text") is None
        model.assert_not_called()


def test_only_the_opening_of_the_article_is_sent():
    """Sending a whole article would multiply the cost of the cheapest step."""
    _, chain = run_with("crackers", content="x" * 9000)

    assert len(chain.seen["content"]) == IMAGE_SUBJECT_SOURCE_CHARS


def test_the_override_reaches_the_prompt():
    generator = ImageGenerator.__new__(ImageGenerator)
    article = {"title": "Mars debuts Cheez-It Protein", "content": ""}

    with patch.object(ImageGenerator, "generate_image", return_value={}) as generate:
        generator.generate_image_for_article(
            article, theme_override="stacked square crackers"
        )

    assert "stacked square crackers" in generate.call_args.kwargs["theme"]


def test_no_override_leaves_the_keyword_table_in_charge():
    generator = ImageGenerator.__new__(ImageGenerator)
    article = {"title": "Krispy Kreme unveils Churro Doughnut Dots", "content": ""}

    with patch.object(ImageGenerator, "generate_image", return_value={}) as generate:
        generator.generate_image_for_article(article)

    assert "doughnut" in generate.call_args.kwargs["theme"].lower()
