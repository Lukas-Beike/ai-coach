from backend.providers.claude_models import setting_family

AI_PROVIDER = "openai"


def turn_ai_provider(model: str | None) -> str:
    """The provider a turn's stored model goes to: anthropic for a Claude family."""
    return "anthropic" if setting_family(model) else AI_PROVIDER
