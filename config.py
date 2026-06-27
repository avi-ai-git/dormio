"""Central configuration for Dormio.

One place for the runtime model registry, the moderation model, the Langfuse
switch, the rate limits, and the app metadata. Read once from the environment,
used everywhere.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ModelOption:
    """One entry in the runtime model selector."""

    key: str          # stable internal id used in code and session state
    label: str        # what a traveller sees in the dropdown
    provider: str     # openrouter, mistral, or ollama
    model_id: str     # the provider's own model identifier
    notes: str = ""   # short description for the help text


# The models a traveller can pick from. One per integration pattern on purpose: an
# aggregator (OpenRouter), a direct European API (Mistral), and a self-hostable
# open-weight model (Ollama Cloud). The model only puts night-train facts into words,
# it never decides the route, so the choice changes the voice, not the answer. Slugs
# are env-overridable so they can be corrected at deploy time without touching code.
RUNTIME_MODELS: dict[str, ModelOption] = {
    "claude-haiku-4.5": ModelOption(
        key="claude-haiku-4.5",
        label="Claude Haiku 4.5 (fast, default)",
        provider="openrouter",
        model_id=os.getenv("MODEL_CLAUDE_HAIKU", "anthropic/claude-haiku-4.5"),
        notes="Default. Quick and warm, through OpenRouter.",
    ),
    "mistral-large": ModelOption(
        key="mistral-large",
        label="Mistral Large (direct)",
        provider="mistral",
        model_id=os.getenv("MODEL_MISTRAL_LARGE", "mistral-large-latest"),
        notes="A strong European model, called directly.",
    ),
    "gpt-oss-120b": ModelOption(
        key="gpt-oss-120b",
        label="GPT-OSS 120B (open weight)",
        provider="ollama",
        model_id=os.getenv("MODEL_GPT_OSS", "gpt-oss:120b"),
        notes="Open-weight model on Ollama Cloud.",
    ),
}

DEFAULT_RUNTIME_MODEL = os.getenv("DEFAULT_RUNTIME_MODEL", "claude-haiku-4.5")

# Mistral Moderation screens user input. Kept separate from the chat selector.
MODERATION_MODEL = os.getenv("MODERATION_MODEL", "mistral-moderation-latest")

# Provider endpoints and credentials.
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MISTRAL_BASE_URL = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "https://api.ollama.com")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

# Observability. Langfuse only. It is off unless its key is present, so the app
# never blocks on a tracing call.
LANGFUSE_ENABLED = (
    bool(os.getenv("LANGFUSE_PUBLIC_KEY"))
    and os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"
)
TRACING_PROJECT = os.getenv("LANGFUSE_PROJECT", "dormio")

# Rate limiting, used by the input-safety layer.
RATE_LIMIT_MIN_SECONDS = float(os.getenv("RATE_LIMIT_MIN_SECONDS", "3"))
RATE_LIMIT_MAX_PER_SESSION = int(os.getenv("RATE_LIMIT_MAX_PER_SESSION", "60"))

# App metadata.
APP_TITLE = os.getenv("APP_TITLE", "Dormio")
APP_VERSION = os.getenv("APP_VERSION", "3.0.0")


def runtime_model_labels() -> list[str]:
    """Selector labels with the default first."""
    ordered = [DEFAULT_RUNTIME_MODEL] + [k for k in RUNTIME_MODELS if k != DEFAULT_RUNTIME_MODEL]
    return [RUNTIME_MODELS[k].label for k in ordered if k in RUNTIME_MODELS]


def model_by_label(label: str) -> ModelOption:
    """Resolve a selector label back to its model, falling back to the default."""
    for option in RUNTIME_MODELS.values():
        if option.label == label:
            return option
    return RUNTIME_MODELS[DEFAULT_RUNTIME_MODEL]


def model_by_key(key: str) -> ModelOption:
    """Resolve an internal key to its model, falling back to the default."""
    return RUNTIME_MODELS.get(key, RUNTIME_MODELS[DEFAULT_RUNTIME_MODEL])
