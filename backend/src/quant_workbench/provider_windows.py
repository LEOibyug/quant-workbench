"""Calendar-month request windows with exclusive ends and atomic assembly."""
import pandas as pd
from quant_workbench.market_data import schedule


def quarter_windows(start, end):
    cursor, stop = pd.Timestamp(start), pd.Timestamp(end)
    if cursor >= stop:
        raise ValueError('开始日期必须早于结束日期')
    while cursor < stop:
        boundary = min(cursor + pd.DateOffset(months=3), stop)
        yield cursor.date(), boundary.date()
        cursor = boundary


def fetch_windows(request, fetch, *, daily=False, progress=None):
    windows = list(quarter_windows(request.start, request.end))
    frames = []
    completed_rows = 0
    for index, (start, end) in enumerate(windows, 1):
        if schedule(str(start), str(end)).empty:
            continue
        prefix = f'区间 {index}/{len(windows)} · {start}—{end}'
        def report(stage, done=0, total=None, unit='条行情'):
            if progress:
                progress(f'{prefix} · {stage}', completed_rows + done, None, unit)
        report('准备下载')
        part = fetch(request.model_copy(update={'start': start, 'end': end}), progress=report)
        frames.append(part)
        completed_rows += len(part)
    if not frames:
        raise ValueError('所选区间没有交易日行情')
    frame = pd.concat(frames, ignore_index=True)
    keys = ['symbol', 'day' if daily else 'timestamp']
    # Identical boundary duplicates are harmless; conflicting prices are not.
    frame = frame.drop_duplicates()
    if frame.duplicated(keys).any():
        raise ValueError('分段行情存在冲突的重复记录，未保存不一致数据')
    return frame.sort_values(keys[::-1]).reset_index(drop=True)
