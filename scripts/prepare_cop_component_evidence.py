"""Classify issuer-confirmed components without upgrading unverified ex-dates."""
import hashlib,json
from pathlib import Path
ROOT=Path('docs/research-results')


def main():
    announcements=json.loads((ROOT/'2026-09-22-cop-announcements.json').read_text())
    vendor=json.loads((ROOT/'2026-09-22-cop-dividend-api.json').read_text())['events']
    definitions=[('2024-03-01','2024-02-19','fourth-quarter-and-full-year-2023-results',[(.58,'ordinary_dividend'),(.2,'variable_return_of_cash')]),('2024-06-03','2024-05-13','first-quarter-2024-results',[(.58,'ordinary_dividend'),(.2,'variable_return_of_cash')]),('2024-09-03','2024-08-12','second-quarter-2024-results',[(.58,'ordinary_dividend'),(.2,'variable_return_of_cash')]),('2024-12-02','2024-11-11','third-quarter-2024-results',[(.78,'ordinary_dividend')]),('2025-03-03','2025-02-17','fourth-quarter-and-full-year-2024-results',[(.78,'ordinary_dividend')])]
    rows=[]
    for pay,record,key,parts in definitions:
        source=next(a for a in announcements if key in a['url'])
        excerpt=next(p for p in source['excerpts'] if 'payable' in p and 'stockholders of record' in p)
        for rate,kind in parts:
            matches=[v for v in vendor if v['payable_date']==pay and v['rate']==rate]
            assert len(matches)==1
            e=matches[0]
            rows.append(dict(vendor_id=e['id'],payable_date=pay,issuer_record_date=record,vendor_record_date=e['record_date'],vendor_ex_date=e['ex_date'],amount_per_share=rate,issuer_classification=kind,issuer_url=source['url'],issuer_sha256=source['sha256'],excerpt=excerpt,record_date_conflict=record!=e['record_date'],classification_confirmed=True,exchange_ex_date_verified=False,book_ready=False))
    rule=Path('artifacts/research/cop-dividends/finra-11140.txt');text=rule.read_text();a=text.index('(a) Designation');b=text.index('Selected Notices:',a)
    out=dict(components=rows,rule_evidence=dict(url='https://www.finra.org/rules-guidance/rulebooks/finra-rules/11140',sha256=hashlib.sha256(rule.read_bytes()).hexdigest(),excerpt=text[a:b],scope='General rule, not COP exchange designation'),book_ready=False)
    (ROOT/'2026-09-22-cop-components-confirmed.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print('Classified',len(rows),'components; record-date conflicts',sum(r['record_date_conflict'] for r in rows))

if __name__=='__main__':main()
