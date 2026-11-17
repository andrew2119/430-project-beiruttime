# Operational audit read adapter

`routes.py:router` is the additive read adapter. `routes.py:run` closes its bounded clients. `definition.json` describes the composition contract without activating discovery before the runtime supports this lane. The composition owner must expose the versioned router, mount the versioned contracts package and attach the lifecycle callback. No database, migration or financial journal is owned here.

The identity dependency authenticates each read before and after the bounded owner calls. Owners independently enforce current record permissions and assignments. Each source is called once, with no retry or fallback. The adapter validates the whole owner envelope, exact reader, query, organization, source revision, row scope, timestamps, totals and pagination before exposing references. Exceptions and private owner error bodies are never included in responses.
