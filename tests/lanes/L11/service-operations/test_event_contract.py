import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from bt_contracts_core.models import EventEnvelope
from L11.conftest import ROOT


def contract_root():
    source = ROOT / 'packages/contracts-service/directory'
    return source if source.is_dir() else Path('/opt/domain-contracts/bt_contracts/service/directory')


def test_four_care_fixture_envelopes_match_strict_receipt_only_contract():
    source = contract_root()
    spec = importlib.util.spec_from_file_location('l11_event_data_contract', source / 'events.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = {}
    for name in ('directory-published', 'directory-choice-saved', 'movement-published', 'movement-selected'):
        event = EventEnvelope.model_validate_json((source / 'fixtures' / (name + '.v1.json')).read_text())
        payload = module.CareEventData.model_validate(event.data)
        assert set(payload.model_dump()) == {'resource_id', 'revision'}
        assert event.source == module.PRODUCERS[event.type]
        observed[event.type] = event.source
        for invalid in ({**event.data, 'revision': True}, {**event.data, 'revision': 0},
                        {**event.data, 'revision': 1.0}, {**event.data, 'revision': 1.5},
                        {**event.data, 'revision': 2147483648}, {**event.data, 'resource_id': 'not-a-uuid'},
                        {**event.data, 'recipient_id': str(event.id)}):
            with pytest.raises(ValidationError):
                module.CareEventData.model_validate(invalid)
    assert observed == module.PRODUCERS
    schema = json.loads((source / 'event-data.schema.v1.json').read_text())
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == {'resource_id', 'revision'}
    assert schema['properties']['revision']['maximum'] == 2147483647
