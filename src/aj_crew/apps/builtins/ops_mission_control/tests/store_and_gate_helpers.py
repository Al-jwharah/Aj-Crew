"""Shared base class for the ops-mission-control store and gate tests (``test_store_and_gate*.py``).

``_HomeIsolated`` redirects ``AJCREW_HOME`` to a fresh temp dir around each test, so no
store or ledger write reaches the real data home.
"""

import shutil
import tempfile
import unittest
from pathlib import Path


class _HomeIsolated(unittest.TestCase):
    """Redirects the data home so store/ledger writes land in a temp dir."""

    def setUp(self):
        import os

        self.tmp = Path(tempfile.mkdtemp())
        self._prev_home = os.environ.get("AJCREW_HOME")
        os.environ["AJCREW_HOME"] = str(self.tmp)
        # config_dir() caches; clear the caches these modules read through.
        from aj_crew.config import loader

        for candidate in ("config_dir", "_config_dir"):
            fn = getattr(loader, candidate, None)
            if fn is not None and hasattr(fn, "cache_clear"):
                fn.cache_clear()

    def tearDown(self):
        import os

        if self._prev_home is None:
            os.environ.pop("AJCREW_HOME", None)
        else:
            os.environ["AJCREW_HOME"] = self._prev_home
        from aj_crew.config import loader

        for candidate in ("config_dir", "_config_dir"):
            fn = getattr(loader, candidate, None)
            if fn is not None and hasattr(fn, "cache_clear"):
                fn.cache_clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _signal(native_id="alarm/x", title="something broke", source="cloudwatch", **kw):
        from aj_crew.apps.builtins.ops_mission_control.backend import models

        return models.Signal.create(source=source, native_id=native_id, title=title, **kw)
