#!/usr/bin/env python3
"""Import the curated starter references through the running app's public API.
Re-run safely: the library deduplicates image contents by SHA-256.
"""
import argparse
import json
import pathlib
import urllib.request
import urllib.error

SOURCES = [
    ('文博文创', '文博非遗', ['文创产品','包装礼盒'], '特列季亚科夫画廊纪念品', '艺术图案、纪念品包装', 'https://www.behance.net/gallery/62844811/Souvenir-packaging', 'Anna Hain; ceramics: Svetlana Sedlova'),
    ('文博文创', '文博非遗', ['品牌视觉','文创产品'], 'MIT Museum 博物馆视觉', '几何、模块、字体系统', 'https://www.pentagram.com/work/mit-museum', 'Pentagram'),
    ('旅游纪念品', '文旅', ['包装礼盒','IP 插画'], 'Venchi 旅行零售包装', '城市天际线、插画、旅行', 'https://www.behance.net/gallery/243008741/Venchi-Travel-Retail-Packaging', 'Heymon Wong'),
    ('旅游纪念品', '文旅', ['文创产品','包装礼盒'], 'Berlin 城市纪念品', '几何、包豪斯、明信片', 'https://www.behance.net/gallery/56902107/City-project', 'Kalyani KB'),
    ('地域礼盒', '文旅', ['包装礼盒','IP 插画'], 'CITY CHOMP BOX 胡志明市礼盒', '城市、街头美食、线描', 'https://www.behance.net/gallery/205869125/CITY-CHOMP-BOX-HCMC-EDITION', 'Door Creative'),
    ('地域礼盒', '文旅', ['包装礼盒','IP 插画'], 'Paris 城市礼盒', '巴黎、城市图案、日夜', 'https://www.behance.net/gallery/24946313/Gift-box', 'Studio10Design'),
    ('食品饮料包装', '食品饮料', ['品牌视觉','包装礼盒'], 'Root & Relish 食品品牌', '自然、手作食品、品牌包装', 'https://www.behance.net/gallery/219957351/Root-Relish-Brand-Identity-Packaging-Design', 'Julia Nikolaeva / Alina Matveeva'),
    ('食品饮料包装', '食品饮料', ['包装礼盒','IP 插画'], 'Portuguese sardines 沙丁鱼包装', '鱼、罐头、插画', 'https://www.behance.net/gallery/201974139/Packaging-design-for-Portuguese-sardines-Food', 'PacPac Studio / Veronika Kulish / Anastasia Volkova / Alex Smirnov'),
    ('茶酒礼赠', '茶酒礼赠', ['包装礼盒'], '茗山意白茶礼盒', '山水、东方、茶', 'https://www.behance.net/gallery/175479143/-Mingshanyi-white-tea-gift-box-design', 'AZHI / 平上去入品牌创意（发布：LIU LIU）'),
    ('茶酒礼赠', '茶酒礼赠', ['包装礼盒','IP 插画'], '茗緻茶礼盒', '花卉、橙色、绘画', 'https://www.behance.net/gallery/201465923/Tea-Gift-Box-Packaging-Design', '特旺設計 TERWANG / Felicia Lei'),
    ('品牌视觉', '生活方式', ['品牌视觉','包装礼盒'], 'Noire et Or 品牌视觉', '黑金、字体、克制', 'https://www.behance.net/gallery/241758783/Noire-et-Or-Brand-Identity-Packaging', 'David Odakpo'),
    ('品牌视觉', '生活方式', ['品牌视觉','文创产品'], 'Matcha 品牌视觉', '抹茶、复古字体、自然配色', 'https://www.behance.net/gallery/98429403/Matcha-Brand-Identity-Merch-Packaging-Design', 'Dusan Kovacevic / House of Maelstrom'),
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8765')
    parser.add_argument('--output', default='outputs/reference-seed')
    args = parser.parse_args()
    out = pathlib.Path(args.output); out.mkdir(parents=True, exist_ok=True)
    def api(path, payload=None, method=None):
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        request = urllib.request.Request(args.api + '/api/references' + path, data=data, method=method,
            headers={'Content-Type':'application/json'} if data else {})
        with urllib.request.urlopen(request, timeout=200) as response:
            return json.load(response)
    report = {'target':48, 'sources':[], 'items':[]}
    existing = {item['id']: item for item in api('?limit=100')['items']}
    curation = json.loads(pathlib.Path(__file__).with_name('reference-seed-curation.json').read_text())
    for source_index, (theme, industry, types, title, keywords, url, author) in enumerate(SOURCES):
        entry = {'theme':theme, 'title':title, 'url':url, 'ids':[], 'errors':[]}
        try:
            imported = api('/import-url', {'url':url, 'limit':4})
            entry['errors'] = imported.get('errors', [])
            for index, item in enumerate(imported['items']):
                values = {'title':f'{title} · {index+1}', 'industries':[industry], 'designTypes':types,
                    'tags':[theme, *keywords.split('、')], 'notes':'首批参考策展；仅记录视觉方向，作品权利归原作者。',
                    'rightsStatus':'未提供可复用授权；仅作视觉参考，请回到作品页核实使用范围。'}
                values.update(description=curation[source_index]['descriptions'][index], colors=curation[source_index]['colors'])
                if author: values['author'] = author
                previous = existing.get(item['id'], {})
                updated = previous if previous.get('userEditedFields') else api('/'+item['id'], values, 'PATCH')
                entry['ids'].append(item['id'])
                report['items'].append(updated)
                with urllib.request.urlopen(args.api + updated['thumbnailUrl'], timeout=30) as response:
                    (out / (item['id']+'.jpg')).write_bytes(response.read())
        except Exception as error:
            entry['errors'].append({'message':str(error)})
        report['sources'].append(entry)
        report['count'] = len({i['id'] for i in report['items']})
        (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"{theme} / {title}: {len(entry['ids'])} 张，累计 {report['count']} / 48", flush=True)
    print(str(out/'report.json'), flush=True)

if __name__ == '__main__': main()
