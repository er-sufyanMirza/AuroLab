"""
scripts/validate_startup.py — AuroLab pre-flight check.
Run before starting the backend to verify all imports and dependencies.

Usage:
    python scripts/validate_startup.py
    python scripts/validate_startup.py --fix    # auto-creates missing dirs
"""
from __future__ import annotations

import sys
import importlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

ok_count = fail_count = warn_count = 0

def ok(msg):
    global ok_count
    ok_count += 1
    print(f"  {GREEN}✓{RESET}  {msg}")

def fail(msg, hint=""):
    global fail_count
    fail_count += 1
    print(f"  {RED}✗{RESET}  {msg}")
    if hint:
        print(f"     {YELLOW}→ {hint}{RESET}")

def warn(msg):
    global warn_count
    warn_count += 1
    print(f"  {YELLOW}⚠{RESET}  {msg}")

def check_import(label, module, attr=None):
    try:
        mod = importlib.import_module(module)
        if attr:
            getattr(mod, attr)
        ok(f"{label}")
        return True
    except ImportError as e:
        fail(f"{label}", f"pip install {module.split('.')[0]}")
        return False
    except AttributeError as e:
        fail(f"{label}: {e}")
        return False

print(f"\n{BOLD}{CYAN}AuroLab Pre-flight Check{RESET}")
print("=" * 55)

# ── 1. Python version ─────────────────────────────────────────────────────────
print(f"\n{BOLD}Python{RESET}")
vi = sys.version_info
if vi >= (3, 10):
    ok(f"Python {vi.major}.{vi.minor}.{vi.micro}")
else:
    fail(f"Python {vi.major}.{vi.minor} (need 3.10+)")

# ── 2. Core dependencies ──────────────────────────────────────────────────────
print(f"\n{BOLD}Core dependencies{RESET}")
deps = [
    ("FastAPI",               "fastapi",              "FastAPI"),
    ("Uvicorn",               "uvicorn",              None),
    ("Pydantic v2",           "pydantic",             "BaseModel"),
    ("Streamlit",             "streamlit",            None),
    ("Groq client",           "groq",                 "Groq"),
    ("ChromaDB",              "chromadb",             None),
    ("sentence-transformers", "sentence_transformers","SentenceTransformer"),
    ("FlashRank",             "flashrank",            None),
    ("rank-bm25",             "rank_bm25",            None),
    ("httpx",                 "httpx",                None),
    ("structlog",             "structlog",            None),
    ("PyMuPDF (fitz)",        "fitz",                 None),
    ("pandas",                "pandas",               None),
    ("plotly",                "plotly",               None),
    ("PyBullet",              "pybullet",             None),
    ("python-multipart",      "multipart",            None),
    ("rapidfuzz",             "rapidfuzz",            None),
]
for label, module, attr in deps:
    check_import(label, module, attr)

# ── 3. AuroLab modules ────────────────────────────────────────────────────────
print(f"\n{BOLD}AuroLab core modules{RESET}")

# New root core/ modules
core_mods = [
    ("Protocol Templates",  "services.translation_service.core.protocol_templates",  "list_templates"),
    ("Opentrons Exporter",  "services.translation_service.core.opentrons_exporter",  "export_opentrons_script"),
    ("Report Generator",    "services.translation_service.core.report_generator",    "generate_html_report"),
    ("Protocol Diff",       "services.translation_service.core.protocol_diff", "diff_protocols"),
    ("Reagent Inventory",   "services.translation_service.core.reagent_inventory",   "ReagentInventory"),
    ("Workflow Engine",     "services.translation_service.core.workflow_engine", "WorkflowEngine"),
    ("Batch Generator",     "services.translation_service.core.batch_generator",     "BatchGenerator"),
    ("Export Bundle",       "services.translation_service.core.export_bundle",       "create_export_bundle"),
    ("Protocol Notes",      "services.translation_service.core.protocol_notes",      "ProtocolNotesStore"),
    ("Param Validator",     "services.translation_service.core.param_validator",     "validate_protocol_params"),
    ("ELN Exporter",        "services.translation_service.core.eln_exporter",        "export_csv"),
    ("Scheduler Jobs",      "services.translation_service.core.scheduler_jobs",      "JobScheduler"),
]
for label, module, attr in core_mods:
    check_import(label, module, attr)

# Services modules
print(f"\n{BOLD}Services modules{RESET}")
svc_mods = [
    ("RAG Engine",          "services.translation_service.core.rag_engine",    "AurolabRAGEngine"),
    ("LLM Engine",          "services.translation_service.core.llm_engine",    "AurolabLLMEngine"),
    ("Chunker",             "services.translation_service.core.chunker",        "chunk_document"),
    ("Protocol Manager",    "services.translation_service.core.protocol_manager","ProtocolManager"),
    ("Execution Orchestr.", "services.execution_service.core.orchestrator",     "execute_protocol"),
    ("Robot Commands",      "services.execution_service.core.robot_commands",   "RobotCommand"),
    ("PyBullet Sim",        "services.execution_service.core.pybullet_sim",     None),
    ("Analytics Engine",    "services.analytics_service.core.analytics_engine", "AnalyticsEngine"),
    ("Vision Engine",       "services.vision_service.core.vision_engine",       "VisionEngine"),
    ("Fleet Scheduler",     "services.orchestration_service.core.scheduler",    "RobotFleet"),
    ("RL Engine",           "services.rl_service.core.rl_engine",               "ProtocolOptimiser"),
]
for label, module, attr in svc_mods:
    check_import(label, module, attr)

# ── 4. API router ─────────────────────────────────────────────────────────────
print(f"\n{BOLD}API layer{RESET}")
check_import("Extensions router", "api.extensions_router", "router")
check_import("Translation routes","services.translation_service.api.routes", "router")

# ── 5. Data directories ───────────────────────────────────────────────────────
print(f"\n{BOLD}Data directories{RESET}")
fix_mode = "--fix" in sys.argv
dirs = [
    ROOT / "data" / "chroma",
    ROOT / "data" / "pdfs",
    ROOT / "logs",
]
for d in dirs:
    if d.exists():
        ok(f"{d.relative_to(ROOT)}")
    elif fix_mode:
        d.mkdir(parents=True, exist_ok=True)
        ok(f"{d.relative_to(ROOT)} (created)")
    else:
        warn(f"{d.relative_to(ROOT)} missing — run with --fix")

# ── 6. Environment ────────────────────────────────────────────────────────────
print(f"\n{BOLD}Environment variables{RESET}")
import os
env_checks = [
    ("GROQ_API_KEY", True,  "Required for LLM generation"),
    ("AUROLAB_SIM_MODE", False, "Optional (default: pybullet)"),
    ("AUROLAB_VISION_BACKEND", False, "Optional (default: mock)"),
]
for var, required, hint in env_checks:
    val = os.getenv(var, "")
    if val:
        display = val[:8] + "..." if len(val) > 8 else val
        ok(f"{var} = {display}")
    elif required:
        fail(f"{var} not set", f"set {var}=your_key_here")
    else:
        warn(f"{var} not set ({hint})")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'=' * 55}")
total = ok_count + fail_count + warn_count
color = GREEN if fail_count == 0 else (YELLOW if fail_count <= 3 else RED)
bar   = "█" * ok_count + "░" * fail_count
print(f"  {color}{bar}{RESET}  {ok_count}/{total} checks passed")
if fail_count == 0:
    print(f"\n  {GREEN}{BOLD}✓ System ready. Start with:{RESET}")
    print(f"    {CYAN}uvicorn main:app --host 0.0.0.0 --port 8080 --reload{RESET}")
    print(f"    {CYAN}streamlit run dashboard/app.py{RESET}")
else:
    print(f"\n  {RED}✗ {fail_count} checks failed. Fix the issues above.{RESET}")
    print(f"    Run:  {CYAN}pip install -r requirements.txt{RESET}")
print(f"{'=' * 55}\n")
sys.exit(0 if fail_count == 0 else 1)