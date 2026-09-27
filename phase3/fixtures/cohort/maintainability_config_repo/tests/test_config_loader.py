import pytest
from src.config_loader import load_database_config, load_cache_config, load_auth_config


def test_default_configs():
    db = load_database_config({})
    assert db["host"] == "localhost"
    assert db["port"] == 5432
    assert db["timeout"] == 30.0
    assert db["ssl"] is False

    cache = load_cache_config({})
    assert cache["host"] == "localhost"
    assert cache["port"] == 6379
    assert cache["timeout"] == 5.0
    assert cache["ssl"] is False

    auth = load_auth_config({})
    assert auth["host"] == "auth.local"
    assert auth["port"] == 8080
    assert auth["timeout"] == 10.0
    assert auth["ssl"] is True


def test_custom_env_configs():
    env = {
        "DB_HOST": "postgres.internal",
        "DB_PORT": "5433",
        "DB_TIMEOUT": "15.5",
        "DB_SSL": "true",
    }
    db = load_database_config(env)
    assert db["host"] == "postgres.internal"
    assert db["port"] == 5433
    assert db["timeout"] == 15.5
    assert db["ssl"] is True


def test_invalid_integer_raises():
    with pytest.raises(ValueError, match="Invalid integer value for DB_PORT"):
        load_database_config({"DB_PORT": "not_an_int"})


def test_invalid_float_raises():
    with pytest.raises(ValueError, match="Invalid float value for CACHE_TIMEOUT"):
        load_cache_config({"CACHE_TIMEOUT": "not_a_float"})
