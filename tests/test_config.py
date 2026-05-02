from customer_context_assistant.config import load_settings


def test_config_loads() -> None:
    settings = load_settings()
    assert settings.app.port == 8787
    assert settings.knowledge_base.source_file.exists()
