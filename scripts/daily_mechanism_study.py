"""Fixed mechanism ablations with cost stress; never rank or select parameters."""
import argparse
import copy
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from quant_workbench.operations import get_operation
from quant_workbench.repository import Repository
from quant_workbench.position import PositionConfig, simulate_positions


def run(task):
    repo = Repository()
    frame = repo.load_dataset(task['dataset_id'])
    cfg = PositionConfig(**task['config'])
    result = simulate_positions(frame, cfg, task['start'], task['end'], daily_bars=True)
    months = {}
    previous = cfg.costs.initial_cash
    for point in result['curve']:
        month = point['date'][:7]
        months[month] = (1 + months.get(month, 0)) * point['equity'] / previous - 1
        previous = point['equity']
    return dict(task=task, metrics=result['metrics'], months=months,
                contributions=result['contributions'], daily_returns=result['daily_returns'])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--operation', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    req=get_operation(Repository(),args.operation)['request']
    base=req['config']
    tasks=[]
    def add(name, changes=None, allocation=None):
        cfg=copy.deepcopy(base); cfg.update(changes or {}); cfg['allocation'].update(allocation or {})
        tasks.append(dict(name=name,dataset_id=req['dataset_id'],start=req['start'],end=req['end'],config=cfg))
    add('baseline')
    add('entry_only',dict(entry_band=.005))
    add('budget_only',dict(capital_mode='risk_budget'))
    add('budget_entry',dict(capital_mode='risk_budget',entry_band=.005))
    # Fixed mechanism ablations only: no parameter search or winner selection.
    for task in list(tasks):
        stress = copy.deepcopy(task)
        stress['name'] += '_double_cost'
        for key in ('spread_bps', 'slippage_bps', 'commission_per_share', 'minimum_commission', 'sell_fee_bps'):
            stress['config']['costs'][key] *= 2
        tasks.append(stress)
    args.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(run,task) for task in tasks]
        for future in as_completed(futures):
            row=future.result();rows.append(row)
            (args.output/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
            m=row['metrics']
            print(row['task']['name'],round(m['return_pct'],3),round(m['max_drawdown_pct'],3),round(m['average_gross_exposure_pct'],2),flush=True)



if __name__=='__main__':
    main()
