import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from router.dispatcher import dispatch
from intent.intentions import Intent
from core.security_manager import ActionDenied

# ─────────────────────────────────────────────
# REQ-006/CA-13: tests reales, colectables por pytest (antes de este REQ este archivo
# reportaba "0 tests collected"). Casos con `channel` real, incluyendo el camino de
# denegación (`ActionDenied`, CA-09) que antes no existía.
# ─────────────────────────────────────────────

DISPATCH_GREEN_CASES = [
    (Intent.CALCULATE, {"operation": "add", "a": 5, "b": 7}),
    (Intent.GET_TIME, {}),
    (Intent.SYSTEM_INFO, {}),
]


@pytest.mark.parametrize("intent, params", DISPATCH_GREEN_CASES)
def test_dispatch_green_intent_returns_string(intent, params):
    call_params = dict(params, channel="desktop")
    result = dispatch(intent, call_params)
    assert isinstance(result, str) and result


def test_dispatch_yellow_intent_denied_raises_action_denied(monkeypatch):
    """CA-09: canal sin adaptador de confirmación (TELEGRAM) deniega una acción YELLOW
    levantando `ActionDenied`, nunca retornando el string '⛔ Acción no autorizada.'."""
    with pytest.raises(ActionDenied):
        dispatch(Intent.SYS_POWER_OFF, {"channel": "telegram"})


def test_dispatch_yellow_intent_desktop_confirmed(monkeypatch):
    """Mismo intent YELLOW, canal DESKTOP con confirmación positiva: ejecuta."""
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "si")
    monkeypatch.setattr("os.system", lambda *_a, **_kw: 0)
    result = dispatch(Intent.SYS_POWER_OFF, {"channel": "desktop"})
    assert isinstance(result, str)


def run_tests():
    print("=== TEST DISPATCHER ===")
    
    # We will just test if dispatching returns a string (success) or throws an exception
    # Some actions might fail because they lack real context or dependencies, we'll try safe ones
    test_cases = [
        (Intent.CALCULATE, {"operation": "add", "a": 5, "b": 7}),
        (Intent.GET_TIME, {}),
        (Intent.SYSTEM_INFO, {}),
    ]

    passed = 0
    for intent, params in test_cases:
        print(f"\nDispatching intent: {intent} with params {params}")
        try:
            result = dispatch(intent, params)
            print(f"  Result: {result[:100]}...") # truncate if long
            if isinstance(result, str):
                passed += 1
                print("  [PASS]")
            else:
                print("  [FAIL] Expected string result")
        except Exception as e:
            print(f"  [ERROR] {e}")

    print(f"\nResults: {passed}/{len(test_cases)} passed.")

if __name__ == "__main__":
    run_tests()
