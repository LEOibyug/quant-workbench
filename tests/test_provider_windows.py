from datetime import date
import pandas as pd
import pytest
from quant_workbench.models import ProviderInput
from quant_workbench.provider_windows import quarter_windows, fetch_windows


def test_calendar_windows_are_contiguous_and_exclusive():
    windows = list(quarter_windows('2024-01-31', '2025-03-01'))
    assert windows[0] == (date(2024,1,31), date(2024,4,30))
    assert windows[-1][1] == date(2025,3,1)
    assert all(a[1] == b[0] for a,b in zip(windows,windows[1:]))
    assert all(pd.Timestamp(end) <= pd.Timestamp(start)+pd.DateOffset(months=3) for start,end in windows)


@pytest.mark.parametrize('daily', [False, True])
def test_assembly_and_mid_download_failure(daily):
    calls=[]; updates=[]
    request=ProviderInput(symbols=['AAPL'],start='2024-01-02',end='2024-08-01')
    def fetch(req, progress):
        calls.append((req.start,req.end))
        progress('page',1,None,'bars')
        return pd.DataFrame({'symbol':['AAPL'], 'day' if daily else 'timestamp':[str(req.start)], 'close':[100.]})
    frame=fetch_windows(request,fetch,daily=daily,progress=lambda *a:updates.append(a))
    assert len(frame)==3 and len(calls)==3
    assert updates[-1][1]==3
    def failed(req,progress):
        if req.start.month > 1: raise ValueError('download failed')
        return fetch(req,progress)
    with pytest.raises(ValueError,match='download failed'):
        fetch_windows(request,failed,daily=daily)
