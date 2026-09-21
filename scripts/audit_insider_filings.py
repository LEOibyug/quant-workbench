"""Public Form4 metadata and fixed original-XML access probe; no trading labels."""
import hashlib,json
from pathlib import Path
import xml.etree.ElementTree as ET
import httpx
import pandas as pd
from prepare_adjusted_trend import PATHS
ROOT=Path('docs/research-results');CACHE=Path('artifacts/research/insider-filings')


def parse(xml):
    root=ET.fromstring(xml)
    if root.tag!='ownershipDocument':raise ValueError('Not an ownership XML')
    rows=[]
    for t in root.findall('./nonDerivativeTable/nonDerivativeTransaction'):
        def value(path):return t.findtext(path)
        rows.append(dict(security=value('securityTitle/value'),transaction_date=value('transactionDate/value'),code=value('transactionCoding/transactionCode'),shares=value('transactionAmounts/transactionShares/value'),price=value('transactionAmounts/transactionPricePerShare/value'),acquired_disposed=value('transactionAmounts/transactionAcquiredDisposedCode/value'),post_shares=value('postTransactionAmounts/sharesOwnedFollowingTransaction/value'),ownership=value('ownershipNature/directOrIndirectOwnership/value'),footnote_ids=[n.get('id') for n in t.findall('.//footnoteId')]))
    relationships=[]
    for owner in root.findall('./reportingOwner'):
        # Stable public filer identifier and professional roles only; omit names/addresses.
        rel=owner.find('reportingOwnerRelationship')
        relationships.append(dict(owner_cik=owner.findtext('reportingOwnerId/rptOwnerCik'),roles={e.tag:e.text for e in rel} if rel is not None else {}))
    return dict(document_type=root.findtext('documentType'),issuer_cik=root.findtext('issuer/issuerCik'),issuer_symbol=root.findtext('issuer/issuerTradingSymbol'),period_of_report=root.findtext('periodOfReport'),aff10b5One=root.findtext('aff10b5One'),relationships=relationships,non_derivative_transactions=rows,derivative_transaction_count=len(root.findall('./derivativeTable/derivativeTransaction')),footnote_ids=[n.get('id') for n in root.findall('./footnotes/footnote')],note='Footnote text and legal transaction interpretation not yet verified')


def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    symbols=sorted(set().union(*(set(pd.read_parquet(p).symbol) for p in PATHS.values())))
    summary=[];records={};sources=[];issuers={}
    for symbol in symbols:
        paths=sorted(Path('artifacts/research').glob('**/'+symbol+'-submission.json'))
        if not paths:
            summary.append(dict(symbol=symbol,status='missing cache'));continue
        path=paths[0];x=json.loads(path.read_text());r=x['filings']['recent'];issuers[symbol]=int(x['cik'])
        source=dict(symbol=symbol,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest());sources.append(source)
        rows=[]
        for i,form in enumerate(r['form']):
            if form not in ['4','4/A']:continue
            row={k:r[k][i] if k in r else None for k in ['accessionNumber','filingDate','acceptanceDateTime','primaryDocument','form','reportDate']}
            stamp=row['acceptanceDateTime']
            row['acceptance_valid_utc']=bool(stamp and pd.Timestamp(stamp).tzinfo is not None)
            rows.append(row)
        records[symbol]=sorted(rows,key=lambda r:(r['filingDate'],r['acceptanceDateTime'] or '',r['accessionNumber']))
        summary.append(dict(symbol=symbol,status='metadata only',form4_count=sum(r['form']=='4' for r in rows),amendment_count=sum(r['form']=='4/A' for r in rows),missing_acceptance=sum(not r['acceptance_valid_utc'] for r in rows),earliest_filing=min([r['filingDate'] for r in rows],default=None),latest_filing=max([r['filingDate'] for r in rows],default=None),listed_older_submission_files=len(x['filings'].get('files',[])),complete_history_verified=False))
    probes=[]
    with httpx.Client(timeout=15,follow_redirects=True,headers={'User-Agent':'QuantWorkbench public financial research'}) as client:
        for symbol in ['ACN','ADP','COP']:
            candidates=[r for r in records[symbol] if r['form']=='4' and r['filingDate'].startswith('2025-08')]
            if not candidates:probes.append(dict(symbol=symbol,status='no fixed-month sample'));continue
            row=candidates[0];accn=row['accessionNumber'].replace('-','');name=Path(row['primaryDocument']).name
            url=f'https://www.sec.gov/Archives/edgar/data/{issuers[symbol]}/{accn}/{name}'
            entry=dict(symbol=symbol,metadata=row,url=url);path=CACHE/f'{symbol}-{accn}.xml'
            try:
                if path.exists():content=path.read_bytes();entry['http_status']='cached'
                else:
                    response=client.get(url);entry['http_status']=response.status_code
                    if response.status_code!=200:
                        entry['status']='source unavailable';probes.append(entry);print(symbol,response.status_code,flush=True);continue
                    content=response.content
                parsed=parse(content);assert int(parsed['issuer_cik'])==issuers[symbol]
                path.write_bytes(content);entry.update(status='parsed',parsed=parsed,sha256=hashlib.sha256(content).hexdigest())
            except (httpx.HTTPError,ET.ParseError,ValueError) as exc:entry.update(status='unavailable or invalid',error_type=type(exc).__name__)
            probes.append(entry);print(symbol,entry['status'],flush=True)
    result=dict(status='completed',source_metadata=sources,coverage=summary,filing_metadata=records,probes=probes,formal_applicability='证据不足',note='Recent submissions cache is not complete history; dates alone do not identify purchases or routine behavior')
    (ROOT/'2026-09-22-insider-filings.json').write_text(json.dumps(result,indent=2)+'\n')
    print('issuers',len(summary),'forms',sum(r.get('form4_count',0) for r in summary),'parsed probes',sum(p['status']=='parsed' for p in probes))


if __name__=='__main__':main()
