"""Ex-ante round-trip estimates using only completed prices and intended size."""

import math

from quant_workbench.models import StrategyConfig


def estimate_round_trip(
    price: float,
    volume: float,
    cash: float,
    config: StrategyConfig,
    max_quantity: int | None = None,
) -> dict:
    impact = (config.spread_bps / 2 + config.slippage_bps) / 10000
    buy_price, sell_price = price * (1 + impact), price * (1 - impact)
    quantity = min(math.floor(volume * config.participation), math.floor(cash / buy_price))
    if max_quantity is not None:
        quantity = min(quantity, max_quantity)
    while quantity > 0:
        commission = max(config.minimum_commission, quantity * config.commission_per_share)
        if quantity * buy_price + commission <= cash:
            break
        quantity -= 1
    if quantity <= 0:
        return {"quantity": 0, "round_trip_bps": None}
    fees = 2 * max(config.minimum_commission, quantity * config.commission_per_share)
    fees += quantity * sell_price * config.sell_fee_bps / 10000
    loss = quantity * (buy_price - sell_price) + fees
    return {"quantity": quantity, "round_trip_bps": loss / (quantity * price) * 10000}
