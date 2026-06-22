# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Cost calculation module for LLM token tracking.

Provides CostCalculator for computing USD costs from token counts using
Decimal precision, and ModelPricing dataclass for pricing configuration.
"""

import json
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    """Per-model pricing configuration.

    All prices are per 1 million tokens (USD).

    Attributes:
        model_key: Normalized model name (e.g., "gemini-1.5-flash")
        input_price_per_1m: Input token price per 1M tokens
        output_price_per_1m: Output token price per 1M tokens
        cached_input_price_per_1m: Cached input token price (typically 10% of input)
    """
    model_key: str
    input_price_per_1m: Decimal
    output_price_per_1m: Decimal
    cached_input_price_per_1m: Decimal


class CostCalculator:
    """Calculate LLM costs from token usage.

    Loads pricing from JSON config (custom or default) and provides cost
    calculation with model name normalization and Decimal precision.
    """

    def __init__(self, pricing_config_path: Optional[str] = None):
        """Initialize cost calculator with pricing configuration.

        Args:
            pricing_config_path: Optional path to custom pricing JSON.
                If None, loads bundled default pricing.
        """
        self._pricing: dict[str, ModelPricing] = {}

        try:
            if pricing_config_path:
                # Load custom pricing config
                with open(pricing_config_path, 'r') as f:
                    config = json.load(f)
                logger.info(f"Loaded custom pricing from {pricing_config_path}")
            else:
                # Load default pricing
                config = self._load_default_pricing()
                logger.debug("Loaded default pricing configuration")

            # Parse config into ModelPricing objects
            for model_key, prices in config.items():
                if model_key.startswith('_'):
                    continue  # skip metadata/comment keys (e.g., _metadata)
                try:
                    self._pricing[model_key] = ModelPricing(
                        model_key=model_key,
                        input_price_per_1m=Decimal(str(prices['input_price_per_1m'])),
                        output_price_per_1m=Decimal(str(prices['output_price_per_1m'])),
                        cached_input_price_per_1m=Decimal(str(prices['cached_input_price_per_1m'])),
                    )
                except (KeyError, ValueError) as e:
                    logger.warning(f"Invalid pricing for model {model_key}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Failed to load pricing config: {e}. Using empty pricing.")
            self._pricing = {}

    def calculate_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> Decimal:
        """Calculate cost in USD for a single LLM call.

        Args:
            model_name: Raw model name from API (e.g., "gemini-1.5-flash-002")
            input_tokens: Prompt token count
            output_tokens: Candidate token count
            cached_tokens: Cached input token count (default: 0)

        Returns:
            Total cost in USD (Decimal with 6 decimal places precision)
        """
        # Normalize model name to pricing key
        model_key = self._normalize_model_name(model_name)

        # Look up pricing (fallback to unknown model pricing)
        pricing = self._pricing.get(model_key)
        if not pricing:
            # Try fallback to unknown key
            pricing = self._pricing.get('unknown')
            if not pricing:
                # No pricing available, return zero
                logger.warning(f"No pricing available for model {model_name} (normalized: {model_key})")
                return Decimal('0')

        # Calculate cost: (tokens / 1M) * price_per_1M
        one_million = Decimal('1_000_000')
        input_cost = (Decimal(input_tokens) / one_million) * pricing.input_price_per_1m
        output_cost = (Decimal(output_tokens) / one_million) * pricing.output_price_per_1m
        cached_cost = (Decimal(cached_tokens) / one_million) * pricing.cached_input_price_per_1m

        total_cost = input_cost + output_cost + cached_cost

        # Round to 6 decimal places (sub-cent precision)
        return total_cost.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)

    def _normalize_model_name(self, model_name: str) -> str:
        """Normalize model name to pricing key.

        Strips version suffixes and 'models/' prefix to match stable pricing keys.

        Args:
            model_name: Raw model name (e.g., "models/gemini-1.5-flash-002")

        Returns:
            Normalized model name (e.g., "gemini-1.5-flash")

        Examples:
            "gemini-1.5-flash-002" -> "gemini-1.5-flash"
            "gemini-1.5-pro-latest" -> "gemini-1.5-pro"
            "models/gemini-3-flash" -> "gemini-3-flash"
        """
        # Strip 'models/' prefix if present (Vertex API format)
        if model_name.startswith('models/'):
            model_name = model_name[7:]  # len('models/') = 7

        # Strip version suffixes
        for suffix in ['-002', '-001', '-latest', '-preview']:
            if model_name.endswith(suffix):
                return model_name[:-len(suffix)]

        return model_name

    def _load_default_pricing(self) -> dict:
        """Load default Gemini pricing from bundled JSON file.

        Returns:
            Pricing configuration dict, or empty dict if file not found.
        """
        try:
            default_path = Path(__file__).parent.parent / "pricing" / "default.json"
            with open(default_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Default pricing file not found: {default_path}")
            return {}
        except Exception as e:
            logger.warning(f"Failed to load default pricing: {e}")
            return {}
