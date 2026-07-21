"""Faceted job and hiring-post discovery over the platform Postgres store.

Pure filtering, faceting, and presentation logic lives in :mod:`service` and
:mod:`posts_service` and operates on in-memory objects, so it is unit-testable
without HTTP or a database. :mod:`repository` supplies those objects from
Postgres; :mod:`hope_job_agent.api.discovery` exposes them over the API.
"""
