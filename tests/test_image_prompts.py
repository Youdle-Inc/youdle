"""Regression tests for the image prompt's subject choice and look.

Every case here is a real failure seen on the live blog, not a hypothetical.
"""

import pytest

from image_generator import ImageGenerator


def theme_for(title, content=""):
    """Run only the theme extraction; no API key, no network."""
    generator = ImageGenerator.__new__(ImageGenerator)
    return generator._extract_article_theme({"title": title, "content": content})


def look_at(index, seed=""):
    return ImageGenerator.look_for(index, seed)


# The themes these must never select, quoted from the table so the assertion
# tests the subject chosen rather than the letters in the sentence. ("price
# tags" contains "rice", which is exactly the trap being tested for.)
RICE = "grains of rice"
TEA = "tea leaves"
FISH = "fish fillets"


@pytest.mark.parametrize(
    "title,forbidden,reason",
    [
        ("Grocery prices rise again in September", RICE,
         "'rice' sits inside 'price'; ten of twenty-five posts were illustrated "
         "with bowls of rice"),
        ("Pepperidge Farm launches protein-filled Goldfish", FISH,
         "'fish' sits inside 'Goldfish'; a cracker launch got a salmon fillet"),
        ("Shoppers buy store brands instead of name brands", TEA,
         "'tea' sits inside 'instead'"),
        ("Beyond Meat announces Beyond Steak availability", TEA,
         "'tea' sits inside 'steak'"),
        ("Unite Us and Instacart team up on food as medicine", TEA,
         "'tea' starts 'team', so a start-only boundary is not enough"),
    ],
)
def test_a_keyword_never_matches_inside_a_longer_word(title, forbidden, reason):
    assert forbidden not in theme_for(title), reason


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Welch's adds natural fruit spreads with strawberries", "strawberr"),
        ("Potato prices climb across the Midwest", "potato"),
        ("Tomatoes are cheaper this month", "tomato"),
        ("Krispy Kreme unveils Churro Doughnut Dots", "doughnut"),
        ("Mission Foods expands its chip portfolio", "chip"),
        ("Beyond Meat announces Beyond Steak availability", "meat"),
    ],
)
def test_stems_and_plurals_still_match(title, expected):
    """The table holds stems on purpose; the boundary must not break them."""
    assert expected in theme_for(title).lower()


def test_the_headline_decides_the_subject_not_the_body():
    """A 400-word body always matches something; the title is the subject."""
    theme = theme_for(
        "Krispy Kreme unveils Churro Doughnut Dots",
        "Shoppers comparing coffee and apples will find prices up again, with "
        "cheese and bread also climbing across most stores this month.",
    )

    assert "doughnut" in theme.lower()
    assert "coffee" not in theme.lower()


def test_the_body_is_still_a_fallback_when_the_title_says_nothing():
    theme = theme_for(
        "What changed at the supermarket this week",
        "The price of fresh salmon fell sharply.",
    )

    assert "salmon" in theme.lower()


def test_a_price_story_has_a_subject_of_its_own():
    """The table had no 'price' entry, which is how 'rice' came to serve them."""
    theme = theme_for("Grocery prices rise again in September")

    assert "price tags" in theme.lower() or "receipt" in theme.lower()


def test_a_batch_never_repeats_a_treatment():
    """Hashing each title independently let two posts in one run collide."""
    batch = [look_at(i, seed="week-of-oct-1") for i in range(len(ImageGenerator.STYLE_LOOKS))]

    assert len(set(batch)) == len(batch), batch


def test_the_rotation_is_stable_for_a_position_and_moves_between_runs():
    assert look_at(2, "week-of-oct-1") == look_at(2, "week-of-oct-1"), (
        "a retry must not reshoot differently"
    )
    assert look_at(0, "week-of-oct-1") != look_at(0, "week-of-oct-8"), (
        "consecutive runs should not open the same way"
    )


def test_every_look_is_a_whole_treatment_not_a_dropdown_value():
    """Six coherent looks replaced 96 mixtures of surface, light and angle."""
    for look in ImageGenerator.STYLE_LOOKS:
        assert look.endswith("."), look
        assert len(look.split()) >= 10, f"too thin to direct a photograph: {look}"


def test_the_prompt_carries_the_look_and_the_hard_rules():
    generator = ImageGenerator.__new__(ImageGenerator)
    look = look_at(1, "seed")

    prompt = generator._create_image_prompt(
        "Krispy Kreme unveils Churro Doughnut Dots",
        theme_for("Krispy Kreme unveils Churro Doughnut Dots"),
        look,
    )

    assert look in prompt
    assert "No recognisable people" in prompt
    assert "No real brand names" in prompt
    assert "{look}" not in prompt, "placeholder left unsubstituted"
    # The licence to be interesting has to survive, or the rules alone read as
    # a specification for a catalogue shot.
    assert "negative space" in prompt


def test_a_branded_subject_is_overridden_at_the_point_of_use():
    """Asked for a generic product, the model still answered "a box of
    Cheez-It Protein crackers". The instruction that follows the subject has to
    neutralise it."""
    generator = ImageGenerator.__new__(ImageGenerator)

    prompt = generator._create_image_prompt(
        "Mars Debuts Cheez-It Protein",
        "Focus on a box of Cheez-It Protein crackers.",
        look_at(0),
    )

    assert prompt.index("unbranded packaging") > prompt.index("What to show")
