import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intent.classifier import classify_command
from intent.intentions import Intent

def run_tests():
    print("=== TEST CLASSIFIER ===")
    
    test_cases = [
        ("abre el bloc de notas", Intent.OPEN_APP, {"app_name": "bloc de notas"}),
        ("multiplica 5 por 4", Intent.CALCULATE, {"operation": "multiply", "a": 5.0, "b": 4.0}),
        ("suma 10 mas 15", Intent.CALCULATE, {"operation": "add", "a": 10.0, "b": 15.0}),
        ("busca en google sobre la luna", Intent.SEARCH_WEB, {"query": "la luna"}),
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
