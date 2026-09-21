"""Strict per-filing research extension, with no unverified year extrapolation."""
import json
from pathlib import Path
from liability_burden_features import judge as direct_judge
from audit_liability_components import snapshot

EVIDENCE=Path('docs/research-results/2026-09-22-liability-filing-evidence.json')


def judge(facts,symbol,cutoff,verified=False):
    original=direct_judge(facts,symbol,cutoff,verified)
    if original['computable'] or original.get('reason')!='同申报同日缺Liabilities':return original
    parts=snapshot(facts,cutoff)
    if parts['status']!='derived_candidate':return original
    evidence=next((e for e in json.loads(EVIDENCE.read_text()) if e['symbol']==symbol
                   and e['accession']==parts['accession'] and e['fiscal_end']==parts['end']),None)
    if evidence is None:return dict(original,reason='缺直接负债且该申报分项未原表核实')
    if any(parts['sources'][t]['val']!=v['value_usd'] for t,v in evidence['values'].items()):
        return dict(original,reason='分项与核实原表不符')
    return dict(original,computable=True,burden=parts['candidate_burden'],accession=parts['accession'],
                sources=parts['sources'],derivation='LiabilitiesCurrent + LiabilitiesNoncurrent',
                evidence_sha256=evidence['pdf_sha256'],reason='限定申报原表核实的分项合计；策略适用性未验证')
