import json, os
base = r"D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor\.workflow\.lite-plan\loosefruit-duplicate-delete-2026-05-31"
out = os.path.join(base, "exploration-patterns.json")
data = {"_metadata": {"exploration_angle": "patterns", "exploration_index": "1 of 3", "task_description": "Create loosefruit duplicate deletion feature"}, "relevant_files": [], "integration_points": [], "patterns": [], "constraints": {}, "clarification_needs": {}}
with open(out, "w", encoding="utf-8") as fh: json.dump(data, fh, indent=2, ensure_ascii=False)
print("done")