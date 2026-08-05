import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from intent.classifier import classify_command
from intent.intentions import Intent
from core.security_manager import ChannelType

# ─────────────────────────────────────────────
# REQ-006/CA-13: tests reales, colectables por pytest (antes de este REQ este archivo
# reportaba "0 tests collected" — solo tenía `run_tests()` con prints, sin `assert`).
# Cubren clasificación + recorrido real hasta `resolve()`, con `channel` real por caso,
# no solo la clasificación aislada.
# ─────────────────────────────────────────────

CLASSIFIER_CASES = [
    ("abre el bloc de notas", Intent.OPEN_APP, {"app_name": "bloc de notas"}),
    ("multiplica 5 por 4", Intent.CALCULATE, {"operation": "multiply", "a": 5.0, "b": 4.0}),
    ("suma 10 mas 15", Intent.CALCULATE, {"operation": "add", "a": 10.0, "b": 15.0}),
    ("busca en google sobre la luna", Intent.SEARCH_WEB, {"query": "sobre la luna"}),
    ("cuanto pesa la carpeta documentos", Intent.FOLDER_SIZE, {"path": "documentos"}),
    ("toma una captura", Intent.TAKE_SCREENSHOT, {}),
]


@pytest.mark.parametrize("cmd, expected_intent, expected_params", CLASSIFIER_CASES)
def test_classify_command_intent(cmd, expected_intent, expected_params):
    intent, params = classify_command(cmd)
    assert intent == expected_intent, f"'{cmd}' -> {intent}, esperado {expected_intent}"
    for key, value in expected_params.items():
        assert params.get(key) == value, (
            f"'{cmd}': params[{key!r}]={params.get(key)!r}, esperado {value!r}"
        )


def test_classify_command_unknown_falls_back(monkeypatch):
    """Cuando el clasificador ML devuelve UNKNOWN, `resolve()` no ejecuta ningún intent y
    cae al resolver 'claude' (última instancia). El modelo TF-IDF+SVM real casi nunca
    predice UNKNOWN (fuera de alcance de REQ-006 ajustar su entrenamiento) — se mockea
    `ai_system.predict` para probar el contrato de forma determinista."""
    from intent import classifier as classifier_module

    monkeypatch.setattr(classifier_module.ai_system, "predict", lambda text: "UNKNOWN")
    intent, _params = classify_command("cualquier texto")
    assert intent == Intent.UNKNOWN


def test_classify_then_resolve_desktop_executes_green_intent():
    """CA-13: recorrido real classify_command() -> resolve() -> dispatch(), no solo
    clasificación aislada. CALCULATE es GREEN, ejecuta igual en cualquier canal."""
    from core.resolution import resolve

    result = resolve("suma 3 mas 4", ChannelType.DESKTOP)
    assert result.matched_by == "intent:CALCULATE"
    assert not result.denied


def run_tests():
    print("=== TEST CLASSIFIER ===")
    
    test_cases = [
        ("abre el bloc de notas", Intent.OPEN_APP, {"app_name": "bloc de notas"}),
        ("multiplica 5 por 4", Intent.CALCULATE, {"operation": "multiply", "a": 5.0, "b": 4.0}),
        ("suma 10 mas 15", Intent.CALCULATE, {"operation": "add", "a": 10.0, "b": 15.0}),
        ("busca en google sobre la luna", Intent.SEARCH_WEB, {"query": "sobre la luna"}),
        ("cuanto pesa la carpeta documentos", Intent.FOLDER_SIZE, {"path": "documentos"}),
        ("toma una captura", Intent.TAKE_SCREENSHOT, {}),
    ]

    passed = 0
    for cmd, expected_intent, expected_params in test_cases:
        print(f"\nTesting command: '{cmd}'")
        try:
            intent, params = classify_command(cmd)
            print(f"  Intent: {intent} (Expected: {expected_intent})")
            print(f"  Params: {params} (Expected: {expected_params})")
            
            # Use 'is' or '==' for enums depending on implementation, intent is an Enum
            if intent == expected_intent:
                passed += 1
                print("  [PASS]")
            else:
                print("  [FAIL]")
        except Exception as e:
            print(f"  [ERROR] {e}")

    print(f"\nResults: {passed}/{len(test_cases)} passed.")

if __name__ == "__main__":
    run_tests()
