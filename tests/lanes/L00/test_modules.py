import json
import pytest
from fastapi.testclient import TestClient
from bt_runtime.modules import discover
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_contracts_core.models import Money
from pydantic import ValidationError


def module(tmp_path, *, identifier='L01.proof', route='/v1/proof'):
    root = tmp_path/identifier
    root.mkdir()
    (root/'module.json').write_text(json.dumps({'version':1,'id':identifier,'routes':['routes.py:router'],
        'migrations':['L01_0001_proof.sql'],'fixtures':{},'dependencies':['fastapi']}))
    (root/'L01_0001_proof.sql').write_text('CREATE TABLE module_proof(id integer PRIMARY KEY);')
    (root/'routes.py').write_text(f"from fastapi import APIRouter\nrouter=APIRouter()\n@router.get('{route}')\nasync def proof(): return {{'proof':'discovered'}}\n")
    return root


def test_module_contributes_router_without_central_edit(tmp_path):
    module(tmp_path)
    found=discover(tmp_path)
    assert found[0].id=='L01.proof'
    app=create_app(Settings(database_url='postgresql://unused/unused', modules_path=tmp_path))
    client=TestClient(app)
    try:
        assert client.get('/v1/proof').json()=={'proof':'discovered'}
    finally:
        client.close()


def test_module_path_escape_is_rejected(tmp_path):
    root=module(tmp_path)
    data=json.loads((root/'module.json').read_text())
    data['migrations']=['../../escape.sql']
    (root/'module.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='owned file'):
        discover(tmp_path)


def test_exact_money_refuses_float_and_nonfinite():
    assert Money(amount='12.50',currency='USD').model_dump(mode='json')['amount']=='12.50'
    for value in [12.5,'NaN','Infinity']:
        with pytest.raises(ValidationError):
            Money(amount=value,currency='USD')
