import sys
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.memory_manager import memory

def run_tests():
    print("=== TEST MEMORY (UnifiedMemory) ===")
    passed = 0
    total = 3

    try:
        print("\nTesting UnifiedMemory store...")
        memory.store("El color favorito del usuario es el azul verdoso oscuro",
                      user_id="test_user", category="test", importance=0.5)
        print("  [PASS] Stored in UnifiedMemory")
        passed += 1
    except Exception as e:
        print(f"  [ERROR] {e}")

    try:
        print("\nTesting UnifiedMemory semantic search...")
        results = memory.search_semantic(
            "Cual es el color favorito del usuario?",
            user_id="test_user", top_k=1, threshold=0.5
        )
        if results:
            print(f"  Found: {results[0].text[:80]}")
            passed += 1
            print("  [PASS] Retrieved semantic memory")
        else:
            print("  [FAIL] No results found")
    except Exception as e:
        print(f"  [ERROR] {e}")

    try:
        print("\nTesting per-user isolation...")
        other = memory.search_semantic(
            "color favorito",
            user_id="other_user", top_k=1, threshold=0.3
        )
        if not other:
            passed += 1
            print("  [PASS] Per-user isolation working")
        else:
            print("  [FAIL] Cross-user leak detected")
    except Exception as e:
        print(f"  [ERROR] {e}")

    print(f"\nResults: {passed}/{total} passed.")

if __name__ == "__main__":
    run_tests()
