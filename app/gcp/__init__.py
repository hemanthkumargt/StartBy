"""Thin, dependency-free clients for the Google Cloud services Cloud 6 uses.

Every service here is called over its public REST API with the stdlib
(urllib) instead of the google-cloud-* client libraries: those pull in
gRPC/protobuf and several hundred MB of imports, which a 1 GB e2-micro
running gunicorn cannot spare. Each module is optional — when its config is
missing or the call fails it degrades (returns False/None and logs) and the
app keeps working with its local behaviour, per the PRD rule that external
calls fail safe."""
