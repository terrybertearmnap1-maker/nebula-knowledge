import pytest

from app.config import Settings
from app.llm import DemoChatModel, build_chat_model


def test_missing_or_blank_api_key_enables_demo_mode() -> None:
    assert Settings(_env_file=None).is_demo is True
    assert Settings(_env_file=None, llm_api_key="").is_demo is True
    assert Settings(_env_file=None, llm_api_key="   ").is_demo is True


def test_demo_mode_can_be_forced_even_with_key() -> None:
    settings = Settings(_env_file=None, llm_api_key="sk-test", demo_mode=True)
    assert settings.is_demo is True
    assert isinstance(build_chat_model(settings), DemoChatModel)


def test_explicit_real_mode_requires_a_key() -> None:
    settings = Settings(_env_file=None, llm_api_key="", demo_mode=False)
    with pytest.raises(ValueError, match="LLM_API_KEY is required"):
        build_chat_model(settings)
