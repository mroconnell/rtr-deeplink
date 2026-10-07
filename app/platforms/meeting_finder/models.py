"""Legacy import path for `app.platforms.resolving.models`.

The code moved to the neutral package `app/platforms/resolving/` (Ryan,
2026-10-06: Meeting Finder is legacy; the shared logic lives outside it).
This module IS the new module (same object in `sys.modules`), not a copy,
so `from app.platforms.meeting_finder.models import X` and a test's
`monkeypatch.setattr(meeting_finder.models, "X", ...)` still hit the one
real definition.
"""

import sys

from app.platforms.resolving import models as _moved

sys.modules[__name__] = _moved
