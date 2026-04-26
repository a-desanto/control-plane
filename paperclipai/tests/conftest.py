import asyncio
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
FIXTURES_DIR = SCHEMAS_DIR / "fixtures"
