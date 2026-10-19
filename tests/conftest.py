import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pytest_addoption(parser):
    parser.addoption("--update-snapshots", action="store_true",
                     help="write parser snapshots for new PDFs and accept every changed one")
