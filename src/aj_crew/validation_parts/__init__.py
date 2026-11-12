"""The owner modules of :mod:`aj_crew.validation`.

``aj_crew.validation`` is the only import path: it imports these owners, lowest layer
first, and serves every name they define. Each owner imports only the owners before it,
and none imports ``aj_crew.validation``. The owner of each responsibility is listed in
the facade's header and in ``docs/system-specs/modules/security.md``.
"""
