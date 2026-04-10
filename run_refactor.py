import os
import re
from pathlib import Path

def process_directory(directory, modules_to_prefix, package_name):
    # Match: (start of line or spaces)(import |from )(one of the modules)(\b)
    # Exclude cases that are already prefixed or dot-prefixed (wait, \s*from \. won't match our regex because we expect exactly module name right after 'from ')
    # Our regex:
    mod_pattern = "|".join(modules_to_prefix)
    pattern = re.compile(rf'^(?P<indent>\s*)(import |from )({mod_pattern})\b', flags=re.MULTILINE)
    
    count_files = 0
    count_replacements = 0
    for root, dirs, files in os.walk(directory):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = Path(root) / f
            try:
                content = path.read_text(encoding='utf-8')
            except Exception:
                continue
                
            new_content, subs = pattern.subn(rf'\g<indent>\g<2>{package_name}.\g<3>', content)
            if subs > 0:
                path.write_text(new_content, encoding='utf-8')
                count_files += 1
                count_replacements += subs
    print(f"{package_name}: Updated {count_files} files with {count_replacements} replacements.")

if __name__ == '__main__':
    base = Path(__file__).resolve().parent
    
    vrptw_modules = [
        'evaluator', 'optimizer', 'orders', 'traffic_api', 'user_input', 
        'vehicles', 'visualization', 'reporter', 'encoder', 'vrptw_study_meta', 
        'vrptw_study_bridge', 'vrptw_panel_schema', 'vrptw_brief_seed', 
        'vrptw_study_prompts', 'vrptw_study_port', 'basic_demo'
    ]
    process_directory(base / 'vrptw_problem', vrptw_modules, 'vrptw_problem')
    
    knapsack_modules = [
        'evaluator', 'instance', 'mealpy_solve', 'knapsack_brief_seed', 
        'knapsack_panel_schema', 'knapsack_study_bridge', 'knapsack_study_port', 
        'knapsack_study_prompts'
    ]
    process_directory(base / 'knapsack_problem', knapsack_modules, 'knapsack_problem')
