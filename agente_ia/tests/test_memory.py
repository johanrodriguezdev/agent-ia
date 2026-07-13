import sys
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.memory_manager import save_memory
from ai.semantic_memory import store_memory, search_similar_memory

def run_tests():
    print("=== TEST MEMORY ===")
    passed = 0
    total = 2
    
    try:
        print("\nTesting semantic memory store...")
        store_memory("El color favorito del usuario es el azul verdoso oscuro")
        print("  [PASS] Stored semantic memory")
        passed += 1
    except Exception as e:
        print(f"  [ERROR] {e}")
        
    try:
        print("\nTesting semantic memory search...")
        result = search_similar_memory("Cual es el color favorito del usuario?", threshold=0.5)
        if result:
            print(f"  Found: {result}")
            passed += 1
            print("  [PASS] Retrieved semantic memory")
        else:
            print("  [FAIL] No results found")
    except Exception as e:
        print(f"  [ERROR] {e}")

    print(f"\nResults: {passed}/{total} passed.")

if __name__ == "__main__":
    run_tests()
