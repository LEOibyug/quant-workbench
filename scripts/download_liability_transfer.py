"""Download frozen new-company data without exposing credentials or changing web datasets."""
import hashlib
import json
from pathlib import Path
import evaluate_alternate_universe as downloader
from prepare_liability_transfer import CIKS

def main():
    downloader.SYMBOLS=list(CIKS)
    downloader.ROOT=Path('artifacts/research/liability-transfer')
    assert not set(CIKS)&{p.name.removesuffix('-facts.json') for p in Path('artifacts/research/asset-pool/sec').glob('*-facts.json')}
    f=downloader.download('2024-08-01','2026-09-01')
    path=downloader.ROOT/'daily.parquet'
    Path('docs/research-results/2026-09-22-liability-transfer-data.json').write_text(json.dumps(dict(symbols=list(CIKS),path=str(path),rows=len(f),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),adjustment='raw',feed='sip',full_corporate_action_audit=False),indent=2)+'\n')

if __name__=='__main__':main()
