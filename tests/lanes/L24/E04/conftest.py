"""Use the candidate's shared migration implementation for local checks."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "runtime" / "src"))
