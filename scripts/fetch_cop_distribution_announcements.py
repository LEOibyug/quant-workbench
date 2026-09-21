"""Read issuer announcements discovered in issuer sitemap, retaining evidence."""
import concurrent.futures
import hashlib
import json
import re
import urllib.request
from html import unescape
from pathlib import Path
CACHE=Path('artifacts/research/cop-dividends')


def main():
    urls=re.findall(r'<loc>(.*?)</loc>',(CACHE/'sitemap.xml').read_text())
    urls=[u for u in urls if '/news-media/story/' in u and any(s in u for s in ['first-quarter-2024-results','second-quarter-2024-results','third-quarter-2024-results','fourth-quarter-and-full-year-2023-results','fourth-quarter-and-full-year-2024-results'])]
    assert len(urls)==5
    def fetch(u):
        path=CACHE/(u.rstrip('/').split('/')[-1]+'.html')
        if not path.exists():path.write_bytes(urllib.request.urlopen(u,timeout=25).read())
        s=path.read_text();s=re.sub(r'<(script|style)\b.*?</\1>','',s,flags=re.S)
        paragraphs=[unescape(re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',p))).strip() for p in re.split(r'</(?:p|li|h[1-6])>',s)]
        excerpts=[p for p in paragraphs if ('dividend' in p.lower() or 'VROC' in p) and ('0.58' in p or '0.20' in p or '0.78' in p or 'ordinary' in p.lower())]
        return dict(url=u,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),excerpts=excerpts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:results=list(executor.map(fetch,urls))
    Path('docs/research-results/2026-09-22-cop-announcements.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    for r in results:
        print(r['url'])
        for p in r['excerpts']:print(p)

if __name__=='__main__':main()
