import importlib.util
import csv
import io
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('import_table', ROOT / 'services/catalog/modules/dealer-import/table.py')
table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(table)


def content(rows):
    out = io.StringIO(newline='')
    csv.writer(out).writerows([table.COLUMNS, *rows])
    return out.getvalue().encode()


def row(**changes):
    value = dict(zip(table.COLUMNS, ['Sample','ساعة طويلة ⌚','R1','2020','Used','Beirut','5000.00','S-1']))
    return list((value | changes).values())


def test_isolates_errors_and_retains_exact_dollars():
    result = table.parse(content([row(),row(brand='=1'),row(price_usd='NaN'),row(year='2101')]))
    assert [r['state'] for r in result] == ['valid','invalid','invalid','invalid']
    assert result[0]['facts']['price_minor'] == 500000
    assert 'serial' not in result[0]['facts']


@pytest.mark.parametrize('price,valid', [('0',False),('0.01',True),('10000000000.00',False),('9999999999.99',True),('1.001',False),('-1',False),('1e2',False)])
def test_price_boundaries(price,valid):
    assert (table.parse(content([row(price_usd=price)]))[0]['state']=='valid') == valid


@pytest.mark.parametrize('count,valid', [(0,False),(1,True),(999,True),(1000,True),(1001,False)])
def test_row_boundaries(count,valid):
    if valid:
        assert len(table.parse(content([row()]*count))) == count
    else:
        with pytest.raises(ValueError): table.parse(content([row()]*count))


def test_normalized_serial_and_safe_exports():
    assert table.parse(content([row(serial=' s-1 ')]))[0]['serial_digest'] == table.parse(content([row(serial='Ｓ１')]))[0]['serial_digest']
    values=['=1',' +2','-3','@x','\t=2','\tplain','plain']
    decoded=list(csv.reader(io.StringIO(table.export_cells([values]))))[0]
    assert all(v.startswith("'") for v in decoded[:-1])
    assert decoded[-1]=='plain'


def test_structure_and_byte_bounds():
    for value in [b'bad',b'\xff',b'x'*1000001,b'brand,model,reference,year,condition,location,price_usd,serial\n"unclosed']:
        with pytest.raises(ValueError): table.parse(value)


@pytest.mark.parametrize('size,state', [(1999,'valid'),(2000,'valid'),(2001,'invalid')])
def test_raw_cell_length_boundary(size,state):
    assert table.parse(content([row(serial=' '*(size-2)+'S1')]))[0]['state'] == state


def test_oversized_cell_does_not_reject_other_rows():
    result = table.parse(content([row(serial=' '*2001+'S1'),row()]))
    assert [item['state'] for item in result] == ['invalid','valid']


@pytest.mark.parametrize('size', [131072, 140000, 990000])
def test_large_cell_is_isolated_within_bounded_table(size):
    payload = content([row(serial='S' * size), row()])
    assert len(payload) <= 1_000_000
    result = table.parse(payload)
    assert [item['state'] for item in result] == ['invalid', 'valid']
    assert result[1]['facts']['price_minor'] == 500000
