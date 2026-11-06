"""What one API call cost, from its usage block. Pure."""

from pipeline import config
from pipeline.agent.contracts import UsageLike


def cost_usd(usage: UsageLike, model: str) -> float:
    prices = prices_for(model, prompt_tokens(usage))
    per_million = (
        usage.input_tokens * prices["input"]
        + (usage.cache_creation_input_tokens or 0) * prices["cache_write"]
        + (usage.cache_read_input_tokens or 0) * prices["cache_read"]
        + usage.output_tokens * prices["output"]
    )
    return per_million / 1_000_000


def prompt_tokens(usage: UsageLike) -> int:
    return (
        usage.input_tokens
        + (usage.cache_creation_input_tokens or 0)
        + (usage.cache_read_input_tokens or 0)
    )


def prices_for(model: str, prompt_size: int) -> dict[str, float]:
    if model not in config.MODEL_PRICES:
        # An unpriced model must never count as free against the budget.
        raise KeyError(f"No price for {model!r}: add it to config.MODEL_PRICES")
    long_card = config.LONG_PROMPT_PRICES.get(model)
    if long_card and prompt_size > long_card[0]:
        return long_card[1]
    return config.MODEL_PRICES[model]
