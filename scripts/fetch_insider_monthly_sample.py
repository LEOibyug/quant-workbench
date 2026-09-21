"""Fixed monthly issuer-linked PDF sample; preserve text for manual transaction review."""
import hashlib,html,json,re,subprocess
from pathlib import Path
import httpx
ROOT=Path('docs/research-results');CACHE=Path('artifacts/research/insider-monthly')


def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    source=ROOT/'2026-09-22-insider-history.json';records=json.loads(source.read_text())['filings']['COP']
    months=[f'2024-{m:02}' for m in range(9,13)]+[f'2025-{m:02}' for m in range(1,9)];results=[]
    with httpx.Client(timeout=20,follow_redirects=True) as client:
        for month in months:
            candidates=sorted([r for r in records if r['form']=='4' and r['filingDate'].startswith(month)],key=lambda r:(r['acceptanceDateTime'],r['accessionNumber']))
            if not candidates:results.append(dict(month=month,status='no sample'));continue
            selected=candidates[0];accn=selected['accessionNumber'];url=f'https://conocophillips.gcs-web.com/sec-filings/sec-filing/4/{accn}';entry=dict(month=month,metadata=selected,detail_url=url)
            page=CACHE/f'{accn}.html';pdf=CACHE/f'{accn}.pdf';txt=CACHE/f'{accn}.txt'
            try:
                if page.exists():content=page.read_text()
                else:
                    r=client.get(url)
                    if r.status_code!=200:entry.update(status='detail unavailable',http_status=r.status_code);results.append(entry);continue
                    content=r.text;page.write_text(content)
                links=re.findall(r'<a\s+[^>]*href="([^"]+)"[^>]*type="application/pdf"[^>]*>',content)
                if len(links)!=1:raise ValueError('Expected unique PDF link')
                pdf_url='https://conocophillips.gcs-web.com'+html.unescape(links[0]);entry['pdf_url']=pdf_url
                if not pdf.exists():
                    if accn=='0000950170-25-101808':data=Path('artifacts/research/insider-filings/cop-fixed.pdf').read_bytes()
                    else:
                        r=client.get(pdf_url)
                        if r.status_code!=200:entry.update(status='PDF unavailable',http_status=r.status_code);results.append(entry);continue
                        data=r.content
                    if not data.startswith(b'%PDF'):raise ValueError('Invalid PDF signature')
                    pdf.write_bytes(data)
                subprocess.run(['pdftotext','-layout',str(pdf),str(txt)],check=True,capture_output=True)
                text=txt.read_text()
                if 'CONOCOPHILLIPS' not in text.upper() or 'Table I -' not in text or 'Explanation of Responses:' not in text:raise ValueError('Missing issuer or tables')
                tables=text[text.index('Table I -'):text.index('Explanation of Responses:')]
                # Footnotes end at the signature block; do not include filer identity/address.
                foot=text[text.index('Explanation of Responses:'):]
                foot=foot.split('** Signature')[0]
                numbered=[]
                for line in foot.splitlines()[1:]:
                    if re.match(r'\s*\d+\.',line):numbered.append(line.strip())
                    elif numbered and line.strip() and not re.search(r' {8,}',line) and not any(w in line for w in ['Attorney','Fact','Commission','Signature']):numbered[-1]+=' '+line.strip()
                entry.update(status='extracted_pending_review',pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),detail_sha256=hashlib.sha256(page.read_bytes()).hexdigest(),table_excerpt=tables,numbered_footnotes=numbered,full_footnote_review_required=True)
            except (httpx.HTTPError,ValueError,subprocess.CalledProcessError) as exc:entry.update(status='failed',error_type=type(exc).__name__)
            results.append(entry);print(month,entry['status'],flush=True)
    payload=dict(status='completed',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),samples=results,note='Fixed samples; PDF extraction is not an automatic transaction classifier')
    (ROOT/'2026-09-22-insider-monthly-sample.json').write_text(json.dumps(payload,indent=2)+'\n')


if __name__=='__main__':main()
