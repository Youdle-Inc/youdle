"""Shared text-generation model configuration.

OpenAI handles article writing, editorial review, and proofreading. Other AI
services (such as Gemini image generation) have their own configuration.

The context window matters here, not just the model name. A full generation
prompt is the editorial template (~3k tokens) plus bounded source text
(~4.5k tokens for a five-source recall roundup) plus few-shot examples pulled
from the learning store (~6k tokens once the store fills up). That is roughly
14k input tokens before the model writes a single word, so an 8k-context model
such as the legacy ``gpt-4`` cannot serve this pipeline at all: it returns
``context_length_exceeded`` and the workflow saves zero posts.
"""

import logging
import os
import re


logger = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = "gpt-4o"
OPENAI_MODEL_PATTERN = re.compile(r"^(gpt|o[0-9])[A-Za-z0-9._-]*$")

# Total context window (input + output) per model, in tokens.
MODEL_CONTEXT_WINDOWS = {
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    "gpt-3.5-turbo": 16385,
    "gpt-4-turbo": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1047576,
    "gpt-4.1-mini": 1047576,
    "gpt-4.1-nano": 1047576,
}

# Maximum completion tokens per model. Requesting more than the model allows is
# rejected with a 400, so the configured ceiling is clamped to this.
MODEL_MAX_OUTPUT_TOKENS = {
    "gpt-4": 8192,
    "gpt-4-32k": 32768,
    "gpt-3.5-turbo": 4096,
    "gpt-4-turbo": 4096,
    "gpt-4o": 16384,
    "gpt-4o-mini": 16384,
    "gpt-4.1": 32768,
    "gpt-4.1-mini": 32768,
    "gpt-4.1-nano": 32768,
}

# Long-form HTML posts need headroom; a low ceiling truncates a post mid-article.
DEFAULT_MAX_TOKENS = 16000

# Unknown models are assumed to be current-generation and large enough. Guessing
# small would block a newer model that works fine.
ASSUMED_CONTEXT_WINDOW = 128000
ASSUMED_MAX_OUTPUT_TOKENS = 4096

# Worst-case prompt (~14k tokens) plus a full long-form post. Below this a model
# cannot complete a generation, so it is rejected up front with an explanation
# instead of failing mid-run as an empty result set.
MIN_CONTEXT_TOKENS = 32000

# Few-shot examples are unbounded blog posts read from the learning store, so
# they are the one prompt section that grows without limit as the store fills.
EXAMPLES_SECTION_MAX_CHARS = 24000


def get_default_openai_model() -> str:
    """Return the configured OpenAI model, falling back when it is unusable.

    This is the *ambient* default: it is read from the environment wherever a
    module is imported or an argparse parser is built, long before anyone has
    asked to generate anything. Raising here punishes every caller for a
    reason unrelated to what it was doing -- a bad OPENAI_MODEL would stop the
    FastAPI app from importing at all, taking /api/health down with it, and
    would kill the CLI even when a valid --model was passed. An explicitly
    supplied model still goes through validate_openai_model and still fails
    loudly, which is where a hard error belongs.
    """

    model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
    try:
        return validate_openai_model(model)
    except ValueError as exc:
        logger.warning(
            "Ignoring unusable OPENAI_MODEL=%r (%s). Falling back to %s.",
            model,
            exc,
            DEFAULT_OPENAI_MODEL,
        )
        return DEFAULT_OPENAI_MODEL


def validate_openai_model(model: str) -> str:
    """Validate and return an OpenAI model ID with a large enough context."""

    model = model.strip()
    if not OPENAI_MODEL_PATTERN.fullmatch(model):
        raise ValueError(
            "The text model must be an OpenAI model ID such as "
            f"{DEFAULT_OPENAI_MODEL}."
        )

    context_window = get_context_window(model)
    if context_window < MIN_CONTEXT_TOKENS:
        raise ValueError(
            f"Model '{model}' has a {context_window}-token context window, but "
            f"blog generation needs at least {MIN_CONTEXT_TOKENS}. A full prompt "
            "is the editorial template plus source text plus learned examples. "
            f"Use a large-context model such as {DEFAULT_OPENAI_MODEL}."
        )
    return model


def get_context_window(model: str) -> int:
    """Return the total context window for a model."""

    return MODEL_CONTEXT_WINDOWS.get(model, ASSUMED_CONTEXT_WINDOW)


def resolve_max_tokens(model: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> int:
    """Clamp the requested completion ceiling to what the model accepts."""

    return min(max_tokens, MODEL_MAX_OUTPUT_TOKENS.get(model, ASSUMED_MAX_OUTPUT_TOKENS))
