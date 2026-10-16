#!/usr/bin/env python
"""
scripts/launch_dashboard.py

Pre-flight check + Streamlit launch for AuroLab dashboard.

Usage:
    python scripts/launch_dashboard.py
    python scripts/launch_dashboard.py --port 8501 --api http://localhost:8080
"""

import argparse
import subprocess
import sys
from pathlib import Path

import httpx


def check_api(base_url: str) -> bool:
    try:
        r = httpx.get(f"{base_url}/health", timeout=3.0)
        if r.status_code == 200:
            rag = r.json().get("rag", {})
            chunks = rag.get("total_chunks", 0)
            print(f"  API online — {chunks:,} chunks indexed")
            return True
    except Exception as e:
        print(f"  API unreachable: {e}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--api",  default="http://localhost:8080")
    args = parser.parse_args()

    print("\nAuroLab Dashboard — pre-flight check")
    print("=" * 42)

    # Check API
    print(f"\n[1/2] Checking backend API at {args.api}...")
    api_ok = check_api(args.api)
    if not api_ok:
        print("\n  WARNING: API is not reachable.")
        print("  Start it with:")
        print("    uvicorn services.translation_service.main:app --port 8080 --reload")
        print("\n  Dashboard will still launch but will show connection errors.\n")

    # Check packages
    print("\n[2/2] Checking dependencies...")
    missing = []
    for pkg in ["streamlit", "plotly", "pandas", "httpx"]:
        try:
            __import__(pkg)
            print(f"  {pkg} OK")
        except ImportError:
            missing.append(pkg)
            print(f"  {pkg} MISSING")

    if missing:
        print(f"\nInstall missing packages: pip install {' '.join(missing)}")
        sys.exit(1)

    print(f"\nLaunching dashboard on http://localhost:{args.port}")
    print("=" * 42)

    dashboard_path = Path(__file__).parent.parent / "dashboard" / "app.py"
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(dashboard_path),
        "--server.port", str(args.port),
        "--server.headless", "false",
        "--theme.base", "dark",
        "--theme.backgroundColor", "#0a0a0e",
        "--theme.secondaryBackgroundColor", "#0d0d12",
        "--theme.primaryColor", "#7c6af7",
        "--theme.textColor", "#d0d0dc",
    ])
#here we are calling our main function

if __name__ == "__main__":
    main()