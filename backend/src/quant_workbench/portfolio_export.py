"""Tabular, lossless per-asset portfolio snapshots for CSV exports."""

import json


def portfolio_rows(curve):
    for point in curve:
        account = {key: value for key, value in point.items() if key not in {"assets", "positions"}}
        for symbol, asset in point.get("assets", {}).items():
            yield {
                **account,
                "symbol": symbol,
                **{
                    f"asset_{key}": json.dumps(value, ensure_ascii=False)
                    if isinstance(value, dict)
                    else value
                    for key, value in asset.items()
                },
            }
