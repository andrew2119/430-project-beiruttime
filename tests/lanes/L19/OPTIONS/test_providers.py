import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
MODULES = ROOT / 'services/catalog/modules/options'


def load(kind, leaf='schema'):
    spec = importlib.util.spec_from_file_location(f'l19_{kind}_{leaf}', MODULES / kind / f'{leaf}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEXT = {'en': 'Sample finishing', 'ar': 'تشطيب نموذجي'}


def definition(kind):
    return {
        'color': dict(color=TEXT, finish=TEXT, swatch='#123456'),
        'material': dict(material=TEXT, grade='316L', construction='solid'),
        'dial': dict(dial=TEXT, hands=TEXT, markers=TEXT, provenance='original', source_reference='sample-1'),
        'sophistication': dict(interventions=[TEXT], exclusions=[TEXT], required_tests=[TEXT],
                               price_reference='sample-1', price_minor=12345, currency='USD'),
    }[kind]


@pytest.mark.parametrize('kind,component', [('color', 'case'), ('material', 'case'), ('dial', 'dial'),
                                            ('sophistication', 'package')])
def test_provider_exact_roundtrip(kind, component):
    value = definition(kind)
    result = load(kind).validate(value, component)
    assert all(result[key] == val for key, val in value.items())
    with pytest.raises(ValueError):
        load(kind).validate(value, 'movement')


@pytest.mark.parametrize('currency', ['LBP', 'EUR', '', None])
def test_finishing_package_only_usd(currency):
    with pytest.raises(ValidationError):
        load('sophistication').validate({**definition('sophistication'), 'currency': currency}, 'package')


@pytest.mark.parametrize('price', [True, 1.1, '123', -1])
def test_finishing_price_is_integer_cents(price):
    with pytest.raises(ValidationError):
        load('sophistication').validate({**definition('sophistication'), 'price_minor': price}, 'package')


@pytest.mark.parametrize('construction', ['plating', 'coating'])
def test_material_retains_substrate_and_thickness(construction):
    value = {**definition('material'), 'construction': construction}
    with pytest.raises(ValueError):
        load('material').validate(value, 'case')
    value.update(substrate=TEXT, thickness_micrometers=5)
    assert load('material').validate(value, 'case')['construction'] == construction
    value['construction'] = 'solid'
    with pytest.raises(ValueError):
        load('material').validate(value, 'case')


@pytest.mark.parametrize('provenance', ['original', 'aftermarket'])
def test_dial_meaning_retained(provenance):
    value = {**definition('dial'), 'provenance': provenance}
    assert load('dial').validate(value, 'dial')['provenance'] == provenance


@pytest.mark.parametrize('field', ['interventions', 'exclusions', 'required_tests', 'price_reference'])
def test_package_requires_defined_scope(field):
    value = definition('sophistication')
    del value[field]
    with pytest.raises(ValueError):
        load('sophistication').validate(value, 'package')


@pytest.mark.parametrize('input_value,expected', [('0', 0), ('1.01', 101), ('١٢٣٫٤٥', 12345),
                                                 ('9999999999.99', 999999999999)])
def test_exact_dollar_input(input_value, expected):
    assert load('color', 'offerings').dollar_cents(input_value) == expected


@pytest.mark.parametrize('value', ['1.001', '-1', '1e3', '1,000', 'nan', '10000000000', ''])
def test_invalid_dollar_input(value):
    with pytest.raises(ValueError):
        load('color', 'offerings').dollar_cents(value)


@pytest.mark.parametrize('kind', ['color', 'material', 'dial', 'sophistication'])
def test_staff_form_contract(kind):
    form = load('color', 'offerings').form(kind)
    assert form['schema_version'] == 'catalog.offering-form.v1'
    assert form['money_storage'] == 'integer_cents'
    for text in form['states'].values():
        assert text['en'] and text['ar']
    if kind == 'sophistication':
        assert form['details_schema']['properties']['currency']['const'] == 'USD'


def test_legacy_currency_not_active():
    active = load('color', 'offerings').active_definition
    assert not active('sophistication', {'details': {'currency': 'LBP'}})
    assert active('sophistication', {'details': {'currency': 'USD'}})


def test_published_form_fixtures_match_provider():
    import json
    provider = load('color', 'offerings')
    fixture = json.loads((MODULES / 'color/fixtures/offering-forms.v1.json').read_text())
    assert fixture['synthetic'] is True
    assert fixture['forms'] == [provider.form(kind) for kind in provider.DETAILS]


def test_receipt_schema_and_outcome_fixtures():
    import json
    from bt_contracts_core.errors import ErrorEnvelope
    provider = load('color', 'offerings')
    fixtures = MODULES / 'color/fixtures'
    assert json.loads((fixtures / 'offering-receipt.schema.v1.json').read_text()) == provider.OfferingReceipt.model_json_schema()
    fixture = json.loads((fixtures / 'offering-outcomes.v1.json').read_text())
    cases = {case['name']: case for case in fixture['cases']}
    assert set(cases) == {'success', 'denied', 'stale', 'lost_response'}
    assert fixture['synthetic'] is True
    success = provider.OfferingReceipt.model_validate(cases['success']['response'])
    for name in ['denied', 'stale']:
        error = ErrorEnvelope.model_validate(cases[name]['response'])
        assert error.error.details['message_ar']
    lost = cases['lost_response']
    assert lost['response'] is None and lost['http_status'] is None
    assert lost['operation_id'] == success.operation_id
    assert provider.OfferingReceipt.model_validate(lost['recovered_response']) == success
