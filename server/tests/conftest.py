import os
import sys
import tempfile
from pathlib import Path

# app.py reads its config at import time, so set it before any test imports it.
os.environ.setdefault("SHAREDL_TOKEN", "t" * 40)
os.environ.setdefault("SHAREDL_WORK_DIR", tempfile.mkdtemp(prefix="sharedl-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
