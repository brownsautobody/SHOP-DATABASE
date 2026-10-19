import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# tests never touch data/: the app and tools get a throwaway data folder (read when db.session is first imported)
os.environ["SHOP_DATA_DIR"] = tempfile.mkdtemp(prefix="shopdb-tests-")
os.environ.pop("DATABASE_URL", None)


def pytest_addoption(parser):
    parser.addoption("--update-snapshots", action="store_true",
                     help="write parser snapshots for new PDFs and accept every changed one")
