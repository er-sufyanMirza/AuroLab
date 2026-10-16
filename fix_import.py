"""
fix_imports.py — Run this ONCE from AuroLab/ project root.
Fixes all import paths in new core/ modules to match your project layout.

Usage:
    python fix_imports.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent
print("AuroLab Import Fixer")
print("=" * 50)

FIXES = [
    # (file, old_import, new_import)

    # batch_generator.py
    ("core/batch_generator.py",
     "from core.llm_engine import _build_system_prompt, _build_user_prompt",
     "from services.translation_service.core.llm_engine import _build_system_prompt, _build_user_prompt"),

    ("core/batch_generator.py",
     "from execution.core.isaac_sim_bridge import SimMode",
     "from services.execution_service.core.isaac_sim_bridge import SimMode"),

    ("core/batch_generator.py",
     "from execution.core.orchestrator import execute_protocol",
     "from services.execution_service.core.orchestrator import execute_protocol"),

    # llm_reflection.py
    ("core/llm_reflection.py",
     "from execution.core.orchestrator import execute_protocol",
     "from services.execution_service.core.orchestrator import execute_protocol"),

    ("core/llm_reflection.py",
     "from execution.core.isaac_sim_bridge import SimMode",
     "from services.execution_service.core.isaac_sim_bridge import SimMode"),

    # workflow_engine.py
    ("core/workflow_engine.py",
     "from execution.core.orchestrator import execute_protocol",
     "from services.execution_service.core.orchestrator import execute_protocol"),

    ("core/workflow_engine.py",
     "from execution.core.isaac_sim_bridge import SimMode",
     "from services.execution_service.core.isaac_sim_bridge import SimMode"),

    # extensions_router.py
    ("api/extensions_router.py",
     "from core.registry import ProtocolEntry",
     "from services.translation_service.core.registry import ProtocolEntry"),

    ("api/extensions_router.py",
     "from execution.core.orchestrator import execute_protocol",
     "from services.execution_service.core.orchestrator import execute_protocol"),

    ("api/extensions_router.py",
     "from execution.core.isaac_sim_bridge import SimMode",
     "from services.execution_service.core.isaac_sim_bridge import SimMode"),

    # tests/test_phase8_extensions.py
    ("tests/test_phase8_extensions.py",
     "from translation_service.core.protocol_manager import ProtocolManager",
     "from services.translation_service.core.protocol_manager import ProtocolManager"),
]

changed = 0
for filepath, old, new in FIXES:
    path = ROOT / filepath
    if not path.exists():
        print(f"  SKIP (not found): {filepath}")
        continue
    src = path.read_text(encoding="utf-8")
    if old in src:
        src = src.replace(old, new)
        path.write_text(src, encoding="utf-8")
        print(f"  FIXED: {filepath}")
        print(f"         {old[:60]}...")
        changed += 1
    else:
        # Already fixed or different version
        if new in src:
            print(f"  OK (already fixed): {filepath}")
        else:
            print(f"  SKIP (pattern not found): {filepath}")

print()
print(f"Done — {changed} replacements made.")
print()
print("Now run:")
print("  python mock_test.py")
print("  uvicorn main:app --host 0.0.0.0 --port 8080 --reload")