import os

# Must run before any test module imports backend.app.workflows.graph, so the
# graph is compiled with the fast in-memory checkpointer rather than opening
# a real langgraph_state.db file per test run. Production defaults to the
# persistent SQLite-backed checkpointer instead (see graph.py) so a paused
# HITL review survives a server restart.
os.environ.setdefault("CHECKPOINT_BACKEND", "memory")

# Must run before any test module imports backend.app.db.database, so tests
# read/write a dedicated file instead of the same controlplane.sqlite3 a
# locally running dev server would be using (or leaving stray test rows in).
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_controlplane.sqlite3")
