"""Reconcile original report text with SEC component candidates; no trading changes."""
import hashlib
import json
import re
from pathlib import Path

ROOT=Path('docs/research-results')


def main():
    candidates=json.loads((ROOT/'2026-09-22-liability-components.json').read_text())['rows']
    evidence=[]
    for symbol,year in [('VZ',2021),('VZ',2022),('VZ',2023),('VZ',2024),('ORCL',2024)]:
        stem=Path('artifacts/research/liability-filings')/f'VZ-{year}' if symbol=='VZ' else Path('artifacts/research/payout-filings/ORCL-2024')
        pdf=stem.with_suffix('.pdf');txt=stem.with_suffix('.txt')
        url=(f'https://www.verizon.com/about/sites/default/files/{year}-Annual-Report-on-Form-10-K.pdf' if year==2021 else f'https://www.annualreports.com/HostedData/AnnualReportArchive/v/NYSE_VZ_{year}.pdf') if symbol=='VZ' else 'https://www.annualreports.com/HostedData/AnnualReportArchive/o/NYSE_ORCL_2024.pdf'
        r=next(x for x in candidates if x['symbol']==symbol and x.get('end','').startswith(str(year)))
        labels={'Assets':'Total assets','LiabilitiesCurrent':'Total current liabilities','LiabilitiesNoncurrent':'Total long-term liabilities' if symbol=='VZ' else 'Total non-current liabilities'}
        matches=[]
        for number,page in enumerate(txt.read_text().split('\f'),1):
            if all(label in page for label in labels.values()):matches.append((number,page))
        assert len(matches)==1,(symbol,year,len(matches))
        page_number,page=matches[0]
        # Preserve the complete statement page, including date/unit headings.
        values={}
        for tag,label in labels.items():
            line=next(line for line in page.splitlines() if re.match(r'\s*'+re.escape(label)+r'\s',line))
            nums=re.findall(r'\d[\d,]*',line[len(line)-len(line.lstrip()):].split(label,1)[1])
            value=int(nums[0].replace(',',''))*1_000_000
            assert value==r['sources'][tag]['val'],(symbol,year,tag,value,r['sources'][tag]['val'])
            values[tag]=dict(value_usd=value,line=line.strip(),sec_source=r['sources'][tag])
        assert values['LiabilitiesCurrent']['value_usd']+values['LiabilitiesNoncurrent']['value_usd']==r['component_total']
        evidence.append(dict(symbol=symbol,fiscal_end=r['end'],accession=r['accession'],url=url,pdf_page=page_number,pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),statement_text=page,values=values,liability_sum=r['component_total'],burden=r['candidate_burden'],validation='Report values match same-filing SEC components; not historical issuer continuity or strategy validation'))
    (ROOT/'2026-09-22-liability-filing-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print([(r['symbol'],r['fiscal_end'],r['pdf_page'],r['liability_sum']) for r in evidence])

if __name__=='__main__':main()
