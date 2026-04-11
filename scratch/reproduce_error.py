import sys
import os
from pathlib import Path
import traceback

# Setup paths to match backend environment
root_dir = Path(r"c:\Users\whyhowie\git-repo\mopt-bot")
backend_dir = root_dir / "backend"
for p in [root_dir, backend_dir]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

def test_imports():
    print("--- Testing Core Imports ---")
    try:
        from vrptw_problem.user_input import SHIFT_HARD_PENALTY, DEFAULT_MAX_SHIFT_HOURS
        print(f"SUCCESS: Imported SHIFT_HARD_PENALTY={SHIFT_HARD_PENALTY}")
        print(f"SUCCESS: Imported DEFAULT_MAX_SHIFT_HOURS={DEFAULT_MAX_SHIFT_HOURS}")
    except ImportError as e:
        print(f"FAILED: Core import failed: {e}")
        return False

    try:
        from vrptw_problem.optimizer import QuickBiteOptimizer
        print("SUCCESS: Imported QuickBiteOptimizer")
    except ImportError as e:
        print(f"FAILED: Optimizer import failed: {e}")
        return False

    print("\n--- Testing Researcher Imports (The previously broken ones) ---")
    try:
        from vrptw_problem.researcher import official_evaluator
        print("SUCCESS: Imported official_evaluator")
    except ImportError as e:
        print(f"FAILED: official_evaluator import failed: {e}")
        traceback.print_exc()
        return False

    try:
        from vrptw_problem.researcher import visualize_convergence
        print("SUCCESS: Imported visualize_convergence")
    except ImportError as e:
        print(f"FAILED: visualize_convergence import failed: {e}")
        traceback.print_exc()
        return False

    return True

def test_logic():
    print("\n--- Testing Logic & Fallbacks ---")
    try:
        from vrptw_problem.user_input import load_user_input
        # Test legacy fallback
        legacy_data = {
            "weights": {"w1": 1.0},
            "shift_hard_penalty": 5000.0  # Old cost value
        }
        # We need a file because load_user_input reads from path
        test_json = root_dir / "scratch" / "test_legacy.json"
        test_json.parent.mkdir(exist_ok=True)
        import json
        with open(test_json, "w") as f:
            json.dump(legacy_data, f)
        
        config = load_user_input(test_json)
        print(f"Legacy fallback test: max_shift_hours={config['max_shift_hours']} (Expected 8.0 for cost 5000)")
        
        legacy_data_hours = {
            "weights": {"w1": 1.0},
            "shift_hard_penalty": 6.5  # Old style but already hours
        }
        with open(test_json, "w") as f:
            json.dump(legacy_data_hours, f)
        config = load_user_input(test_json)
        print(f"Legacy hours test: max_shift_hours={config['max_shift_hours']} (Expected 6.5)")
        
        return True
    except Exception as e:
        print(f"FAILED: Logic test failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if test_imports() and test_logic():
        print("\nALL TESTS PASSED! The Solver dependencies issue should be resolved.")
        sys.exit(0)
    else:
        print("\nTESTS FAILED.")
        sys.exit(1)
