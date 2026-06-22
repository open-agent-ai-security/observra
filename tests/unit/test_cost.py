# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for cost module."""

from decimal import Decimal

from observra.core.cost import CostCalculator


def test_cost_calculator_default_pricing():
    """Test that CostCalculator loads default pricing."""
    calculator = CostCalculator()

    # Should have loaded pricing from default.json
    assert len(calculator._pricing) > 0


def test_cost_calculator_known_model():
    """Test cost calculation for known model."""
    calculator = CostCalculator()

    cost = calculator.calculate_cost("gemini-2.5-flash", 1000, 500)

    # Cost should be positive for known model
    assert cost > Decimal('0')
    assert isinstance(cost, Decimal)


def test_cost_calculator_unknown_model():
    """Test cost calculation for unknown model returns zero."""
    calculator = CostCalculator()

    cost = calculator.calculate_cost("unknown-model-xyz", 100, 50)

    # Unknown model should return zero cost
    assert cost == Decimal('0')


def test_model_name_normalization():
    """Test model name normalization strips version suffixes."""
    calculator = CostCalculator()

    normalized = calculator._normalize_model_name("gemini-1.5-flash-002")
    assert normalized == "gemini-1.5-flash"

    normalized = calculator._normalize_model_name("gemini-1.5-pro-latest")
    assert normalized == "gemini-1.5-pro"

    normalized = calculator._normalize_model_name("gemini-2.5-flash-preview")
    assert normalized == "gemini-2.5-flash"


def test_model_name_strip_models_prefix():
    """Test model name normalization strips 'models/' prefix."""
    calculator = CostCalculator()

    normalized = calculator._normalize_model_name("models/gemini-3-flash")
    assert normalized == "gemini-3-flash"

    normalized = calculator._normalize_model_name("models/gemini-1.5-pro-002")
    assert normalized == "gemini-1.5-pro"


def test_cost_decimal_precision():
    """Test that cost calculation returns 6 decimal places."""
    calculator = CostCalculator()

    cost = calculator.calculate_cost("gemini-2.5-flash", 1000, 500)

    # Check that result has 6 decimal places (sub-cent precision)
    cost_str = str(cost)
    if '.' in cost_str:
        decimal_places = len(cost_str.split('.')[1])
        assert decimal_places <= 6
