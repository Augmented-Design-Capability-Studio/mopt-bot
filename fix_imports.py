import os
from pathlib import Path

def fix_imports(root_dir):
    root_path = Path(root_dir)
    for filepath in root_path.rglob('*.py'):
        if 'venv' in filepath.parts or '.git' in filepath.parts:
            continue
        try:
            content = filepath.read_text(encoding='utf-8')
            new_content = content
            
            # Fix "from problem package import prefix_something"
            for pfx in ['vrptw_', 'knapsack_']:
                for mod in ['study_bridge', 'study_port', 'study_prompts', 'panel_schema', 'brief_seed', 'study_meta']:
                    # "import study_bridge" -> "import study_bridge"
                    new_content = new_content.replace(f"import {pfx}{mod}", f"import {mod}")
                    # "study_bridge." -> "study_bridge."
                    new_content = new_content.replace(f"{pfx}{mod}.", f"{mod}.")
                    # "vrptw_panel_patch" -> "panel_patch" (functions)
                    new_content = new_content.replace(f"{pfx}panel_patch_response_json_schema", "panel_patch_response_json_schema")
                    
            if new_content != content:
                filepath.write_text(new_content, encoding='utf-8')
                print(f"Fixed imports in: {filepath}")
        except Exception as e:
            pass

if __name__ == '__main__':
    fix_imports(r"c:\Users\whyhowie\git-repo\mopt-bot")
