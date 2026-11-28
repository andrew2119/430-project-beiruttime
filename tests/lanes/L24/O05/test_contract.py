import json
from pathlib import Path

import pytest

from services.orders.modules.custody.adapter import Adapter
from services.orders.modules.custody.domain import Facts
from services.orders.modules.custody.repository import Custody
from test_custody import CONTEXT, NOW, Provider


ROOT = Path("packages/contracts-orders/custody")
FIXTURES = json.loads((ROOT / "fixtures" / "cases.json").read_text())["cases"]


def validate_schema(value, schema, root):
    if "$ref" in schema:
        return validate_schema(value, root["$defs"][schema["$ref"].rsplit("/", 1)[1]], root)
    if "oneOf" in schema:
        matches = 0
        for branch in schema["oneOf"]:
            try:
                validate_schema(value, branch, root)
                matches += 1
            except AssertionError:
                pass
        assert matches == 1
        return
    if "const" in schema:
        assert value == schema["const"]
    if "enum" in schema:
        assert value in schema["enum"]
    kind = schema.get("type")
    if kind == "object":
        assert isinstance(value, dict) and set(schema.get("required", [])) <= value.keys()
        if schema.get("additionalProperties") is False:
            assert value.keys() <= schema["properties"].keys()
        for key, child in value.items():
            validate_schema(child, schema["properties"][key], root)
    elif kind == "string":
        import re
        assert isinstance(value, str) and schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 10000)
        if "pattern" in schema:
            assert re.search(schema["pattern"], value)
        if schema.get("format") == "date-time":
            from services.orders.modules.custody.domain import instant
            instant(value)
    elif kind == "integer":
        assert type(value) is int and schema.get("minimum", 0) <= value <= schema.get("maximum", 2**53 - 1)
    elif kind == "array":
        assert isinstance(value, list) and len(value) <= schema.get("maxItems", 100)
        if schema.get("uniqueItems"):
            assert len(set(value)) == len(value)
        for item in value:
            validate_schema(item, schema["items"], root)
    elif kind == "null":
        assert value is None


@pytest.mark.parametrize("case", FIXTURES, ids=lambda case: case["name"])
def test_published_request_response(case, tmp_path):
    schema = json.loads((ROOT / "command.schema.json").read_text())
    validate_schema(case["request"], schema, schema)
    provider = Provider(Facts(**case["facts"]))
    provider.unavailable = case["provider_unavailable"]
    custody = Custody(tmp_path / "contract.sqlite", provider, lambda: NOW)
    adapter = Adapter(custody)
    status, response = adapter.call("command", CONTEXT, command=case["request"])
    assert status == case["expected_status"]
    assert response == case["expected_response"]
    if case["name"] == "lost_response":
        assert adapter.call("command", CONTEXT, command=case["request"]) == (status, response)
    if case["name"] == "timeout":
        provider.unavailable = False
        assert adapter.call("command", CONTEXT, command=case["request"])[0] == 200
