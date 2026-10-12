"""Token and cost accounting.

Token counts are an approximation (about four characters per token), which is accurate enough
for budgeting and for comparing variants. The mock models carry illustrative prices so the cost
dashboards have something to compute. Real-provider prices come from configuration.
"""
from ..config import settings

# USD per million tokens (input, output). Illustrative values for the mock models only.
MOCK_PRICING = {
    "mock-large": (3.00, 15.00),
    "mock-small": (0.80, 4.00),
}


def count_tokens(text: str) -> int:
    return max(1, round(len(text or "") / 4))


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = MOCK_PRICING.get(model, (settings.price_in_per_mtok, settings.price_out_per_mtok))
    return round((tokens_in * price_in + tokens_out * price_out) / 1_000_000, 6)
