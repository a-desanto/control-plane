"""Schema round-trip tests: good fixtures validate, bad fixtures are rejected."""

import json
from pathlib import Path

import jsonschema
import jsonschema.validators
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
FIXTURES_DIR = SCHEMAS_DIR / "fixtures"

SCHEMA_CASES = [
    ("intent@v3.2.json", "intent_good.json", "intent_bad.json"),
    ("workflow_plan@v3.2.json", "workflow_plan_good.json", "workflow_plan_bad.json"),
    (
        "execution_instruction@v3.2.json",
        "execution_instruction_good.json",
        "execution_instruction_bad.json",
    ),
    ("tool_output@v3.2.json", "tool_output_good.json", "tool_output_bad.json"),
]


def _load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def _make_validator(schema: dict) -> jsonschema.protocols.Validator:
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema, format_checker=jsonschema.FormatChecker())


@pytest.mark.parametrize("schema_file,good_fixture,_bad", SCHEMA_CASES)
def test_good_fixture_validates(schema_file: str, good_fixture: str, _bad: str) -> None:
    schema = _load_json(SCHEMAS_DIR / schema_file)
    fixture = _load_json(FIXTURES_DIR / good_fixture)
    validator = _make_validator(schema)
    errors = list(validator.iter_errors(fixture))
    assert errors == [], f"Good fixture {good_fixture!r} failed validation:\n" + "\n".join(
        str(e) for e in errors
    )


@pytest.mark.parametrize("schema_file,_good,bad_fixture", SCHEMA_CASES)
def test_bad_fixture_is_rejected(schema_file: str, _good: str, bad_fixture: str) -> None:
    schema = _load_json(SCHEMAS_DIR / schema_file)
    fixture = _load_json(FIXTURES_DIR / bad_fixture)
    validator = _make_validator(schema)
    errors = list(validator.iter_errors(fixture))
    assert errors, (
        f"Bad fixture {bad_fixture!r} unexpectedly passed validation — "
        "check that the fixture actually violates the schema."
    )
