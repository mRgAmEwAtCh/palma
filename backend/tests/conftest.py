import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="hm-test-"))
os.environ.setdefault("PLAYBOOKS_DIR", str(ROOT / "playbooks"))
os.environ.setdefault("AUTH_DISABLED", "true")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("TIMEZONE", "Europe/Berlin")
os.environ.setdefault("FRONTEND_DIST", str(ROOT / "nonexistent"))
sys.path.insert(0, str(ROOT / "backend"))
