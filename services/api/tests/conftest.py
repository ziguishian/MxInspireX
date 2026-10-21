import sys
import os
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Production never exposes deterministic or placeholder providers. Tests opt
# into the isolated adapters explicitly so they can exercise persistence and
# routing without making network calls.
os.environ["AICS_TEST_MODE"] = "1"
# Node fixtures exchange UTF-8 JSON with Python subprocesses on Windows too.
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
