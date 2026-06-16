"""Test configuration for LangChain adapter tests.

Patches the langchain_core module hierarchy into sys.modules before any test
imports happen, so the adapter can be imported without the optional langchain-core
package installed.

The stub BaseCallbackHandler is a no-op with all required callback methods so
LangChainAdapter's super().__init__() and method overrides succeed.
"""

import sys
import types as _types


# ---------------------------------------------------------------------------
# Create stub langchain_core module hierarchy
# ---------------------------------------------------------------------------

class _StubBaseCallbackHandler:
    """Stub base class for BaseCallbackHandler — no-op implementations of all callbacks."""

    def on_llm_end(self, response, *, run_id, **kwargs):
        pass

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        pass

    def on_llm_new_token(self, token, *, chunk=None, run_id, **kwargs):
        pass

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        pass

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        pass

    def on_tool_end(self, output, *, run_id, **kwargs):
        pass

    def on_tool_error(self, error, *, run_id, **kwargs):
        pass

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        pass

    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        pass

    def on_chain_error(self, error, *, run_id, **kwargs):
        pass


class _StubLLMResult:
    """Stub LLMResult class for type hints."""
    pass


# Build the fake module hierarchy
_lc_mod = _types.ModuleType("langchain_core")
_lc_callbacks_mod = _types.ModuleType("langchain_core.callbacks")
_lc_callbacks_base_mod = _types.ModuleType("langchain_core.callbacks.base")
_lc_outputs_mod = _types.ModuleType("langchain_core.outputs")

_lc_callbacks_base_mod.BaseCallbackHandler = _StubBaseCallbackHandler
_lc_outputs_mod.LLMResult = _StubLLMResult

_lc_mod.callbacks = _lc_callbacks_mod
_lc_callbacks_mod.base = _lc_callbacks_base_mod

# Register all required module paths
sys.modules.setdefault("langchain_core", _lc_mod)
sys.modules.setdefault("langchain_core.callbacks", _lc_callbacks_mod)
sys.modules.setdefault("langchain_core.callbacks.base", _lc_callbacks_base_mod)
sys.modules.setdefault("langchain_core.outputs", _lc_outputs_mod)
