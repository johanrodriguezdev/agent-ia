import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router.dispatcher import dispatch
from intent.intentions import Intent

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
