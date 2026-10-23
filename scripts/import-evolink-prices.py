"""Import the public pricing page's embedded data, without executing its scripts.

Usage: python scripts/import-evolink-prices.py downloaded-pricing.html YYYY-MM-DD
The page expresses text tariffs per 1K tokens, despite its table's 1M header.
"""
import json
import re
import sys
from pathlib import Path
from html.parser import HTMLParser


class PriceTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        if tag == 'td' and self.row is not None:
            self.cell = []

    def handle_data(self, text):
        if self.cell is not None:
            self.cell.append(text)

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
        if tag == 'tr' and self.row:
            self.rows.append(self.row)
            self.row = None


def extract(html):
    flight = ''.join(json.loads(s) for s in re.findall(
        r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html))
    decoder = json.JSONDecoder()
    rows = decoder.raw_decode(flight.split('"rows":', 1)[1])[0]
    pricing = decoder.raw_decode(flight.split('"initialSkuPricing":', 1)[1])[0]

    def clean(value):
        if isinstance(value, str) and value.startswith('$19:props:children:1:props:rows:'):
            parts = value.split(':')[6:]
            target = rows[int(parts[0])]
            for key in parts[1:]:
                target = target[int(key)] if isinstance(target, list) else target[key]
            return clean(target)
        if value == '$undefined':
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if v != '$undefined'}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    keys = ('id', 'name', 'modality', 'unit', 'apiName', 'comingSoon', 'evolinkPrice',
            'minUSD', 'maxUSD', 'fromUSD', 'fallbackTiers', 'highVolumeTiers',
            'tierSkus', 'skuId', 'creditPrice', 'headlineRate', 'expandedRates')
    result = [{k: v for k, v in clean(r).items() if k in keys} for r in rows]
    table = PriceTable()
    table.feed(html)
    for cells in table.rows:
        if len(cells) != 5 or len(cells[1]) < 3:
            continue
        row = next((r for r in result if r['name'] == cells[1][0]), None)
        amounts = [text for text in cells[2] if re.fullmatch(r'\$[0-9.]+', text)]
        if row and amounts:
            # The headline may select a different variant than the default API
            # ID in the embedded product record (e.g. reference-to-video).
            row['apiName'] = cells[1][-1]
            row['displayHeadline'] = dict(label=cells[2][0], usd=float(amounts[0][1:]), unit=cells[2][-1])
    return {'rows': result,
            'skuPrices': pricing['skuPrices']}


if __name__ == '__main__':
    data = extract(Path(sys.argv[1]).read_text(encoding='utf-8'))
    data.update(checkedAt=sys.argv[2], sourceUrl='https://evolink.ai/zh/pricing')
    target = Path(__file__).resolve().parents[1] / 'services/api/app/evolink_price_data.json'
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Imported {len(data["rows"])} public model rows')
