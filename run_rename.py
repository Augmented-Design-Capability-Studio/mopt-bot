import os
import re
from pathlib import Path

def run_refactor(root_dir):
    root_path = Path(root_dir)
    # 1. Update text content in all python files
    for filepath in root_path.rglob('*.py'):
        if 'venv' in filepath.parts or '.git' in filepath.parts:
            continue
        try:
            content = filepath.read_text(encoding='utf-8')
            # Fix imports
            new_content = content.replace('vrptw_problem.', 'vrptw_problem.')
            new_content = new_content.replace('knapsack_problem.', 'knapsack_problem.')
            if new_content != content:
                filepath.write_text(new_content, encoding='utf-8')
                print(f"Updated contents: {filepath}")
        except Exception:
            pass
            
    # 2. Rename files
    for filepath in root_path.rglob('*.py'):
        if 'venv' in filepath.parts or '.git' in filepath.parts:
            continue
        name = filepath.name
        if filepath.parent.name == 'vrptw_problem' and name.startswith('vrptw_'):
            new_name = name.replace('vrptw_', '', 1)
            new_path = filepath.parent / new_name
            os.rename(filepath, new_path)
            print(f"Renamed {filepath} -> {new_path}")
        elif filepath.parent.name == 'knapsack_problem' and name.startswith('knapsack_'):
            new_name = name.replace('knapsack_', '', 1)
            new_path = filepath.parent / new_name
            os.rename(filepath, new_path)
            print(f"Renamed {filepath} -> {new_path}")

if __name__ == '__main__':
    run_refactor(r"c:\Users\whyhowie\git-repo\mopt-bot")
