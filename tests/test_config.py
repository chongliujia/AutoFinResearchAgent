from autofin.config import ModelConfigStore


def test_model_config_store_persists_config_and_secrets(tmp_path):
    config_path = tmp_path / "config.json"
    secrets_path = tmp_path / "secrets.json"
    store = ModelConfigStore(config_path=config_path, secrets_path=secrets_path)

    store.update(
        {
            "provider": "openai-compatible",
            "model": "test-model",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-secret",
            "temperature": 0.1,
        }
    )

    reloaded = ModelConfigStore(config_path=config_path, secrets_path=secrets_path).get()

    assert reloaded.model == "test-model"
    assert reloaded.base_url == "https://api.example.com/v1"
    assert reloaded.api_key == "sk-test-secret"
    assert reloaded.public_view()["api_key_preview"] == "sk-t...cret"
    assert "api_key" not in config_path.read_text()
    assert "sk-test-secret" in secrets_path.read_text()
