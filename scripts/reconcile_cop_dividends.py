"""Issuer history and vendor reconciliation; never infer ex-dates from old footnotes."""
import hashlib,json,re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
ROOT=Path('docs/research-results')
CACHE=Path('artifacts/research/cop-dividends')


class Table(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,t,a):
        if t=='tr':self.row=[]
        if t in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,d):
        if self.cell is not None:self.cell.append(d)
    def handle_endtag(self,t):
        if t in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).replace('\u200b','').split()));self.cell=None
        if t=='tr' and self.row is not None:self.rows.append(self.row);self.row=None


def main():
    source=CACHE/'history.html';parser=Table();parser.feed(source.read_text());issuer=[]
    for row in parser.rows:
        if len(row)!=4:continue
        try:decl,rec,pay=[datetime.strptime(x,'%m/%d/%y').date().isoformat() for x in row[:3]]
        except ValueError:continue
        if not '2021-07-01'<=decl<='2026-09-22':continue
        rate=str(Decimal(row[3].replace('$','')))
        issuer.append(dict(declaration_date=decl,record_date=rec,payable_date=pay,rate=rate))
    vendor=json.loads((ROOT/'2026-09-22-cop-dividend-api.json').read_text())['events']
    reconciled=[]
    for e in vendor:
        matches=[r for r in issuer if (r['record_date'],r['payable_date'],Decimal(r['rate']))==(e['record_date'],e['payable_date'],Decimal(str(e['rate'])))]
        reconciled.append(dict(vendor=e,issuer_matches=matches,amount_record_payment_matched=len(matches)==1,ex_date_independently_verified=False,book_ready=False))
    groups=defaultdict(list)
    for r in reconciled:groups[r['vendor']['ex_date']].append(r)
    multiple=[dict(ex_date=d,ids=[r['vendor']['id'] for r in rs],rates=[r['vendor']['rate'] for r in rs],sum_rate=str(sum((Decimal(str(r['vendor']['rate'])) for r in rs),Decimal(0))),all_issuer_rows_matched=all(r['amount_record_payment_matched'] for r in rs),action='retain separate evidence, do not drop or book before entitlement verification') for d,rs in groups.items() if len(rs)>1]
    unmatched=[r for r in issuer if not any((r['record_date'],r['payable_date'],Decimal(r['rate']))==(e['record_date'],e['payable_date'],Decimal(str(e['rate']))) for e in vendor)]
    old_note='Ex-dividend date is the second business day prior to the record date.'
    assert old_note in source.read_text()
    out=dict(issuer_url='https://www.conocophillips.com/investor-relations/stock-information/dividend-history/',issuer_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),issuer_rows=issuer,vendor_reconciliations=reconciled,multiple_same_ex_date=multiple,unmatched_issuer_rows=unmatched,issuer_note=old_note,book_ready=False,limitations=['Issuer table does not list ex-dates','Dollar symbol does not independently establish USD gross entitlement treatment','Same-date different-rate entries are not duplicates','Vendor special=false does not independently identify distribution legal type'])
    (ROOT/'2026-09-22-cop-dividend-reconciliation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    lines=['# COP分红核对：同日两笔分配与旧除息说明','',
           f"发行人历史表解析{len(issuer)}条（宣告2021-07至2026-09），供应商按process_date三月分段取得{len(vendor)}条。金额/登记日/支付日三字段匹配{sum(r['amount_record_payment_matched'] for r in reconciled)}条；发行人表无匹配{len(unmatched)}条。完整原文哈希和每笔记录保留。",'',
           '|供应商除息日（未独立核实）|各笔金额|合计|发行人金额/日期均匹配|','|---|---|---:|---|']
    for r in multiple:lines.append(f"|{r['ex_date']}|{r['rates']}|{r['sum_rate']}|{r['all_issuer_rows_matched']}|")
    lines+=['','## 不能机械去重或推断日期','',
            '唯一三字段不匹配记录为2025-03-03支付0.78美元：官网登记2025-02-17，供应商登记及除息2025-02-14。金额和支付日一致，登记日冲突未解决，不擅自把一方替换为另一方。','',
            '2024年2月、5月、8月三次同除息日，各有0.58与0.20两笔，发行人历史表也分别列示。按股票+日期只保留一笔会丢掉真实分配；本轮也不会在未核实权利性质时直接合并入账。当前CashDividendBook拒绝同日多笔，可保护重复权益，却需要显式、可审计的多组成分规范化后才适合此类数据。','',
            '历史表脚注仍写“除息日在登记日前两个工作日”。表内没有逐笔除息日；供应商2024-08的两笔ex_date=record_date=08-12，与脚注不一致。不能照此脚注生成全部历史除息日，也不能仅凭供应商日期自动宣布已核实。2024-11登记11-11而供应商除息11-08亦提醒交易/结算假日规则不能粗略套用。','',
            'FINRA Notice 23-15（https://www.finra.org/rules-guidance/notices/23-15）原文明确标准交割T+2改T+1，支持需要考虑制度变化；它不是COP逐笔权益公告。SEC投资者除息页面403，未读取；猜测COP2024季度公告路径404，未将失败请求当原文证据。','',
            '供应商32笔无显式currency，special=false不能证明法律分配性质；发行人金额带$但本轮尚未独立核实USD税前及可变现金回报的具体分类。历史表宣告日可提供进一步逐笔公告入口，不能证明API当时已发布。所有结果book_ready=false，未填补到策略收益。','',
            '这项核查发现了直接影响COP单股回测的两处风险：去重可能漏分配，旧脚注可能错配权益日。接下来需取得逐笔公告/交易所权益时点，并为同日不同组成分保留来源后规范化。此前低负债策略失败结论仍保留其分红遗漏限定，不能据本轮审计宣称翻转。','',
            '复现：环境载入.env运行`scripts/audit_cop_dividend_api.py`，然后`uv run --locked python scripts/reconcile_cop_dividends.py`。密钥未输出，总体目标未完成。']
    (ROOT/'2026-09-22-cop-dividend-reconciliation.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines[:10]))

if __name__=='__main__':main()
