"""Session graph annotations: roles, threads, arrows, persistence."""
from __future__ import annotations

import pytest

from symphony.unified.graph import GraphError, GraphNotes


def test_roles_threads_persist_and_clear(tmp_path):
    path = tmp_path / "graph.json"
    notes = GraphNotes(path)
    assert notes.annotate("a", role="review", thread="  minor   units ") == {
        "role": "review", "thread": "minor units"}
    assert GraphNotes(path).notes_for("a") == {"role": "review", "thread": "minor units"}
    notes.annotate("a", role="", thread="")
    assert GraphNotes(path).notes_for("a") == {}
    with pytest.raises(GraphError):
        notes.annotate("a", role="boss")
    assert len(notes.annotate("b", thread="x" * 99)["thread"]) == 40


def test_edges_reject_self_and_cycles_and_persist(tmp_path):
    path = tmp_path / "graph.json"
    notes = GraphNotes(path)
    notes.add_edge("impl", "review")
    notes.add_edge("review", "ship")
    notes.add_edge("impl", "review")  # duplicate is a no-op
    with pytest.raises(GraphError):
        notes.add_edge("ship", "impl")
    with pytest.raises(GraphError):
        notes.add_edge("impl", "impl")
    assert GraphNotes(path).edges() == [("impl", "review"), ("review", "ship")]
    assert notes.remove_edge("impl", "review") is True
    assert notes.remove_edge("impl", "review") is False


def test_prune_drops_dead_sessions(tmp_path):
    notes = GraphNotes(tmp_path / "graph.json")
    notes.annotate("live", role="main")
    notes.annotate("dead", role="plan")
    notes.add_edge("live", "dead")
    assert notes.prune({"live"}) is True
    assert notes.notes_for("dead") == {}
    assert notes.edges() == []
    assert notes.prune({"live"}) is False
