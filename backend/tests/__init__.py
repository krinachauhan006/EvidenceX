"""Test package.

Isolates the test run from the developer's real database and blob store.

The application builds its engine at import time from environment settings, and
a few code paths (the ``/health`` check, case-delete blob cleanup) use those
defaults directly. Pointing them at throwaway locations here, before anything
imports the app, guarantees tests never touch ``var/evidencex.db`` or
``var/storage``. Pytest imports this package before ``conftest.py``.
"""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["STORAGE_ROOT"] = tempfile.mkdtemp(prefix="evidencex-tests-")
