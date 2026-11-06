from dataclasses import dataclass

import pytest

from pipeline.agent.cost import cost_usd, prompt_tokens


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


def test_haiku_short_prompt_uses_standard_card() -> None:
    usage = Usage(10_000, 10_000, 10_000, 10_000)
    # 0.10 input + 0.125 cache write + 0.01 cache read + 0.50 output, per million each
    expected = 10_000 * (0.10 + 0.125 + 0.01 + 0.50) / 1e6
    assert cost_usd(usage, "claude-haiku-5-5") == pytest.approx(expected)
    assert prompt_tokens(usage) == 30_000


def test_haiku_switches_whole_request_to_long_card_above_100k_prompt_tokens() -> None:
    at_limit = Usage(input_tokens=100_000, output_tokens=1_000)
    over = Usage(input_tokens=60_000, output_tokens=1_000, cache_read_input_tokens=40_001)
    assert cost_usd(at_limit, "claude-haiku-5-5") == pytest.approx(
        (100_000 * 0.10 + 1_000 * 0.50) / 1e6
    )
    assert cost_usd(over, "claude-haiku-5-5") == pytest.approx(
        (60_000 * 0.50 + 40_001 * 0.05 + 1_000 * 2.50) / 1e6
    )


def test_sonnet_has_no_long_prompt_card() -> None:
    usage = Usage(input_tokens=500_000, output_tokens=10_000, cache_read_input_tokens=200_000)
    assert cost_usd(usage, "claude-sonnet-5-5") == pytest.approx(
        (500_000 * 2.00 + 200_000 * 0.10 + 10_000 * 10.00) / 1e6
    )


def test_missing_cache_fields_count_as_zero() -> None:
    assert cost_usd(Usage(input_tokens=1_000), "claude-haiku-5-5") == pytest.approx(0.0001)


def test_unpriced_model_is_never_free() -> None:
    with pytest.raises(KeyError, match="MODEL_PRICES"):
        cost_usd(Usage(input_tokens=1), "claude-unknown-9")
