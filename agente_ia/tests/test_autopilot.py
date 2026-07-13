import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.task_planner import TaskPlanner
from agents.task_executor import TaskExecutor

def run_tests():
    print("=== TEST AUTOPILOT ===")
    
    try:
        planner = TaskPlanner()
        executor = TaskExecutor()
        
        # Test 1: Plan generation
        command = "crea un documento sobre el sistema solar"
        print(f"\nTesting plan generation for: '{command}'")
        
        plan = planner.generate_plan(command)
        if plan:
            print(f"  Generated {len(plan)} steps:")
            for i, step in enumerate(plan):
                print(f"    {i+1}. {step.get('action', 'Unknown')} - {step.get('description', '')}")
            print("  [PASS]")
            
            # Note: We won't test execution directly here because it might invoke real LLM calls
            # that consume tokens or actually create files. We'll just validate the planner.
        else:
            print("  [FAIL] Plan was empty or None")
            
    except Exception as e:
        print(f"  [ERROR] {e}")

if __name__ == "__main__":
    run_tests()
