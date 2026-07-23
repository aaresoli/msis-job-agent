"""Scheduled operations: digests, reminders, reconciliation, backups, metrics.

Every module here holds plain functions that take a :class:`~sqlalchemy.orm.Session`
and return a summary dict. The Celery tasks in
:mod:`hope_job_agent.workers.ops_tasks` and the operator-facing routes in
:mod:`hope_job_agent.api.internal` both call into these, so a scheduled run and
a manual run execute the same code rather than two implementations that drift.
"""
