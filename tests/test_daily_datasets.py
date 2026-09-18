import pandas as pd
import pytest
from quant_workbench.repository import Repository
from quant_workbench.operations import begin_operation, execute_operation, get_operation
from quant_workbench.models import ProviderInput


def test_daily_download_persists_ohlcv_without_minute_conversion(tmp_path, monkeypatch):
    frame = pd.DataFrame(dict(day=['2024-01-02', '2024-01-03'], symbol='TEST',
                              open=100, high=102, low=99, close=101, volume=200000))
    monkeypatch.setattr('quant_workbench.daily_providers.fetch_daily', lambda *a, **k: frame)
    monkeypatch.setattr('quant_workbench.operations.fetch_provider', lambda *a, **k: pytest.fail('minute request'))
    repo = Repository(tmp_path)
    job = begin_operation(repo, 'download')
    execute_operation(repo, job, ProviderInput(symbols=['TEST'], start='2024-01-02', end='2024-01-04', timeframe='1Day'))
    saved = get_operation(repo, job['id'])
    assert saved['status'] == 'completed', saved
    dataset = saved['result']
    assert dataset['timeframe'] == '1Day'
    assert dataset['dates'] == frame.day.tolist()
    pd.testing.assert_frame_equal(repo.load_dataset(dataset['id']), frame[['day', 'symbol', 'open', 'high', 'low', 'close', 'volume']])
    with pytest.raises(ValueError, match='OHLC'):
        repo.save_dataset(frame.assign(high=90), 'bad', 'test', timeframe='1Day')
