"""Bounded private table validation; no cell content in errors."""
import csv
import hashlib
import io
import re
import unicodedata

# The encoded request bound also bounds decoded field allocation.
# Let oversized cells reach row validation instead of rejecting neighboring rows.
csv.field_size_limit(max(csv.field_size_limit(), 1_000_000))

COLUMNS = ['brand', 'model', 'reference', 'year', 'condition', 'location', 'price_usd', 'serial']


def safe_cell(value):
    return "'" + value if value.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@')) else value


def export_cells(rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerows([[safe_cell(str(cell)) for cell in row] for row in rows])
    return output.getvalue()


def parse(content):
    if len(content) > 1_000_000:
        raise ValueError('table_limit')
    try:
        reader = csv.reader(io.StringIO(content.decode('utf-8-sig'), newline=''), strict=True)
        if next(reader, None) != COLUMNS:
            raise ValueError('columns')
        result = []
        for number, cells in enumerate(reader, 1):
            if number > 1000:
                raise ValueError('table_limit')
            valid = len(cells) == len(COLUMNS) and all(
                0 < len(cell.strip()) and len(cell) <= 2000 and not cell.lstrip().startswith(('=', '+', '-', '@'))
                and not any(ord(c) < 32 for c in cell) for cell in cells)
            row = dict(zip(COLUMNS, cells))
            valid = valid and bool(re.fullmatch(r'[0-9]{1,10}(\.[0-9]{1,2})?', row.get('price_usd', '')))
            valid = valid and bool(re.fullmatch(r'(18|19|20)[0-9]{2}|2100', row.get('year', '')))
            if valid:
                dollars, _, cents = row['price_usd'].partition('.')
                price = int(dollars) * 100 + int(cents.ljust(2, '0') or '0')
                valid = 0 < price <= 10**12 and all(len(row[k]) <= n for k, n in [('brand',100),('model',160),('reference',100),('location',160)])
            if not valid:
                result.append({'row': number, 'state': 'invalid'})
                continue
            serial = ''.join(c for c in unicodedata.normalize('NFKC', row['serial']).upper() if c.isalnum())
            if not serial:
                result.append({'row': number, 'state': 'invalid'})
                continue
            facts = {k: row[k] for k in ('brand','model','reference','condition','location')}
            facts.update(year=int(row['year']), price_minor=price, currency='USD', no_documents=True)
            result.append({'row': number, 'state': 'valid', 'facts': facts,
                           'serial_digest': hashlib.sha256(serial.encode()).hexdigest()})
        if not result:
            raise ValueError('empty')
        return result
    except (UnicodeError, csv.Error):
        raise ValueError('invalid_table') from None
