"""Owners composed by :mod:`aj_crew.cli_doctor`.

``aj_crew.cli_doctor`` holds the ``ajcrew doctor`` orchestrator and stays the command's
one import path and patch target. The report rows split out of it live in the modules of
this package, and nothing but ``aj_crew.cli_doctor`` imports one.
:func:`aj_crew._facade_compose.compose` makes every function a module here defines run on
``aj_crew.cli_doctor``'s module globals rather than its own. Tests patch
``cli_doctor.probe_server``, ``.resolve_kiro_cli``, ``._git_line``, ``.KIRO_AGENTS_DIR`` and
many other names; a row that read its owner's globals would keep calling
the unpatched object and the test would pass while exercising nothing, so the doctor stays
ONE namespace, as the one-module file was. Four consequences follow:

* An owner's imports are inert for its functions. It imports standard-library modules
  plainly and names ``aj_crew.cli_doctor`` under ``TYPE_CHECKING``, for the type checker
  and the linter; every name a function reads must exist in ``aj_crew.cli_doctor``, and
  ``test/test_cli_doctor_parts.py`` sweeps every function's bytecode to prove it does.
* No owner defines a module-level value. The doctor's constants stay in
  ``aj_crew.cli_doctor``, so a test that rebinds one there rebinds what every row reads.
* A function's ``__module__`` reads ``aj_crew.cli_doctor`` and it logs through that
  module's ``logger``; only its source file differs, so ``inspect.getsource``, a spawn
  census and a log record's ``filename`` name the owner file.
* The ACP imports the agent-SDK boundary baseline counts stay in ``aj_crew.cli_doctor``.
  An owner reads those names off the facade's globals and imports no ``aj_crew.acp``
  module, not even for type checking.

The owners, and where new work for each goes:

* :mod:`~aj_crew.cli_doctor_parts.model_section` -- the Model section and the audit of
  the agent specs' model pins
* :mod:`~aj_crew.cli_doctor_parts.mcp_sections` -- the MCP Tools probe and repair, and
  MCP Governance
* :mod:`~aj_crew.cli_doctor_parts.host_probes` -- the host probes the families and the
  orchestrator call
* :mod:`~aj_crew.cli_doctor_parts.kas_relay` -- the KAS relay rows
"""
