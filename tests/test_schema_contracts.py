"""Tests for declarative gateway JSON schema contracts."""
from __future__ import annotations

import json
from pathlib import Path
import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "schemas"
ROUTES_SCHEMA_PATH = SCHEMAS_DIR / "gateway-routes.schema.json"
CLIENTS_SCHEMA_PATH = SCHEMAS_DIR / "gateway-clients.schema.json"
PROD_INVENTORY = ROOT / "inventory/production/host_vars/ai-5820-01.yml"


def test_schemas_are_valid_draft202012():
    for schema_path in (ROUTES_SCHEMA_PATH, CLIENTS_SCHEMA_PATH):
        raw = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(raw)


def test_production_routes_and_aliases_conform_to_schema():
    routes_schema = json.loads(ROUTES_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(routes_schema)

    inventory_data = yaml.safe_load(PROD_INVENTORY.read_text(encoding="utf-8"))
    routes = inventory_data.get("orchestrator_gateway_routes", [])
    aliases = inventory_data.get("orchestrator_gateway_model_aliases", {})

    payload = {
        "routes": routes,
        "model_aliases": aliases,
    }
    validator.validate(payload)


def test_production_clients_conform_to_schema():
    clients_schema = json.loads(CLIENTS_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(clients_schema)

    inventory_data = yaml.safe_load(PROD_INVENTORY.read_text(encoding="utf-8"))
    clients = inventory_data.get("orchestrator_gateway_clients", [])

    payload = {
        "clients": clients,
    }
    validator.validate(payload)


def test_schema_rejects_invalid_routes():
    routes_schema = json.loads(ROUTES_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(routes_schema)

    # Missing required 'pool'
    bad_payload = {
        "routes": [{"id": "bad-rule", "match": {}}]
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(bad_payload)

    # Invalid strategy
    bad_strategy = {
        "routes": [{"id": "bad-strat", "pool": "lead", "match": {}, "strategy": "non_existent"}]
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(bad_strategy)


def test_schema_rejects_invalid_clients():
    clients_schema = json.loads(CLIENTS_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(clients_schema)

    # Unknown scope
    bad_client = {
        "clients": [
            {
                "client_id": "bad-scopes",
                "scopes": ["super-admin"],
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(bad_client)

    # Invalid sha256 digest length
    bad_digest = {
        "clients": [
            {
                "client_id": "bad-hash",
                "token_sha256": "12345",
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(bad_digest)
