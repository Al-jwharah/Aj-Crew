"""The cron service's owners, composed by :class:`aj_crew.cron.CronService`.

Each module owns one responsibility and, at import time, imports only modules
listed above it:

* :mod:`~aj_crew.cron_service.schedule` -- when a job fires (next run, due, jitter,
  rendering, time parsing);
* :mod:`~aj_crew.cron_service.model` -- the job record itself;
* :mod:`~aj_crew.cron_service.identity` -- the session key a run presents, the
  principal it names, the memory it runs with;
* :mod:`~aj_crew.cron_service.claims` -- a run's occupancy of its job;
* :mod:`~aj_crew.cron_service.execution` -- a run's deadlines and terminal record;
* :mod:`~aj_crew.cron_service.store` -- ``crons.json``'s format, lock and failure types;
* :mod:`~aj_crew.cron_service.fields` -- what a valid job and a valid update are;
* :mod:`~aj_crew.cron_service.readers` -- read-only views of the store with no
  scheduler running;
* :mod:`~aj_crew.cron_service.folders` -- cron folder definitions;
* :mod:`~aj_crew.cron_service.service` -- the ``CronService`` members the class
  binds by name, one module per responsibility.

:mod:`aj_crew.cron` stays the import and patch surface: every name the flat modules
above hold is re-exported there as the same object (the ``service`` modules hold
``CronService`` members, bound on the class instead), and a name tests patch there is read
by these modules through it on each call (a function-local import, so the module
graph stays acyclic at import time).
"""
