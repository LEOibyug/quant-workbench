"""Verify the manually reviewed template in twelve fixed PDFs; not a general parser."""
import hashlib,json,re
from pathlib import Path
import pandas as pd
ROOT=Path('docs/research-results')


def main():
    path=ROOT/'2026-09-22-insider-monthly-sample.json';x=json.loads(path.read_text());assert len(x['samples'])==12
    labels=[]
    for row in x['samples']:
        assert row['status']=='extracted_pending_review'
        text=row['table_excerpt'];first,second=text.split('Table II -',1)
        assert not re.search(r'\d{2}/\d{2}/\d{4}',first)
        assert 'Stock' in second and 'Units' in second
        transactions=re.findall(r'(\d{2}/\d{2}/\d{4})\s+A\s+(\d+)\s+\(2\)\s+\(2\)',second)
        assert len(transactions)==1
        day,quantity=transactions[0]
        tail=re.search(r'Stock\s+(\d+)\s+\$([\d.]+)\s+([\d,.]+)(?:\(3\))?\s+D',second)
        assert tail and int(tail.group(1))==int(quantity)
        assert any('1-for-1' in f for f in row['numbered_footnotes'])
        assert any('separation from service' in f for f in row['numbered_footnotes'])
        transaction_day=pd.to_datetime(day,format='%m/%d/%Y').strftime('%Y-%m-%d')
        assert transaction_day<=row['metadata']['filingDate']
        assert not re.search(r'Name and Address|\(Street\)',text)
        labels.append(dict(month=row['month'],accession=row['metadata']['accessionNumber'],pdf_sha256=row['pdf_sha256'],acceptance_utc=row['metadata']['acceptanceDateTime'],transaction_day=transaction_day,non_derivative_transactions=0,derivative_transactions=1,code='A',units=int(quantity),reported_derivative_price=tail.group(2),post_units=tail.group(3),deferred_payment_terms=True,active_open_market_purchase_confirmed=False,manual_review_scope='Fixed twelve PDFs plus strict template consistency; no generic Form4 inference'))
    history=json.loads((ROOT/'2026-09-22-insider-history.json').read_text())['filings']['COP']
    all_forms=[r for r in history if r['form']=='4' and '2024-09-01'<=r['filingDate']<'2025-09-01']
    result=dict(status='completed',source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),labels=labels,total_form4_in_interval=len(all_forms),sampled=12,not_reviewed=len(all_forms)-12,limitation='First filing each month oversamples scheduled activity; not representative of all trades or routine-classifier validation')
    (ROOT/'2026-09-22-insider-monthly-review.json').write_text(json.dumps(result,indent=2)+'\n')
    print('reviewed',len(labels),'remaining',len(all_forms)-12)


if __name__=='__main__':main()
