"""Explicit SEC older-file expansion with accession-level conflict preservation."""
import hashlib,json,re
from pathlib import Path
import httpx
ROOT=Path('docs/research-results');CACHE=Path('artifacts/research/insider-history')
FIELDS=['accessionNumber','filingDate','acceptanceDateTime','primaryDocument','form','reportDate']


def records(table):
    for i,form in enumerate(table['form']):
        if form in ['4','4/A']:yield {k:table[k][i] if k in table else None for k in FIELDS}


def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    original=json.loads((ROOT/'2026-09-22-insider-filings.json').read_text());summaries=[];files=[];all_rows={};all_conflicts=[]
    with httpx.Client(timeout=20,headers={'User-Agent':'QuantWorkbench public financial research'}) as client:
        for source in original['source_metadata']:
            symbol=source['symbol'];path=Path(source['path']);payload=json.loads(path.read_text());merged={};conflicts=[]
            def add(row,origin):
                key=row['accessionNumber']
                if key not in merged:merged[key]={**row,'sources':[origin]};return
                old=merged[key]
                for k in FIELDS:
                    if old.get(k) and row.get(k) and old[k]!=row[k]:conflicts.append(dict(symbol=symbol,accession=key,field=k,left=old[k],right=row[k],source=origin))
                    elif not old.get(k) and row.get(k):old[k]=row[k]
                old['sources'].append(origin)
            for r in records(payload['filings']['recent']):add(r,str(path))
            old_count=sum('2019-01-01'<=r['filingDate']<'2025-09-01' for r in merged.values());requested=0;failed=0
            for item in payload['filings'].get('files',[]):
                if item['filingFrom']>='2025-09-01' or item['filingTo']<'2019-01-01':continue
                name=item['name'];assert re.fullmatch(r'CIK\d{10}-submissions-\d+\.json',name)
                requested+=1;target=CACHE/name;url='https://data.sec.gov/submissions/'+name
                if target.exists():data=json.loads(target.read_text());status='cached'
                else:
                    try:response=client.get(url)
                    except httpx.HTTPError as exc:
                        files.append(dict(symbol=symbol,url=url,error=type(exc).__name__));failed+=1;continue
                    status=response.status_code
                    if status!=200:files.append(dict(symbol=symbol,url=url,status=status));failed+=1;continue
                    data=response.json();target.write_text(json.dumps(data,separators=(',',':'))+'\n')
                for r in records(data):add(r,str(target))
                files.append(dict(symbol=symbol,url=url,status=status,path=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),listing=item))
            selected=sorted([r for r in merged.values() if '2019-01-01'<=r['filingDate']<'2025-09-01'],key=lambda r:(r['filingDate'],r['accessionNumber']))
            all_rows[symbol]=selected;all_conflicts.extend(conflicts)
            summaries.append(dict(symbol=symbol,cik=payload['cik'],prior_interval_records=old_count,expanded_interval_records=len(selected),added_unique_records=len(selected)-old_count,first_interval_filing=min([r['filingDate'] for r in selected],default=None),missing_acceptance=sum(not r.get('acceptanceDateTime') for r in selected),files_requested=requested,files_failed=failed,conflicts=len(conflicts),historical_identity_and_completeness_verified=False))
            print(symbol,old_count,'->',len(selected),'files',requested,'failed',failed,'conflicts',len(conflicts),flush=True)
    result=dict(status='completed',interval=['2019-01-01','2025-09-01'],summary=summaries,files=files,filings=all_rows,conflicts=all_conflicts,original_metadata_sha256=hashlib.sha256((ROOT/'2026-09-22-insider-filings.json').read_bytes()).hexdigest())
    (ROOT/'2026-09-22-insider-history.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
