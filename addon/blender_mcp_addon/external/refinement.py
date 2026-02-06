"""Refinement session state management.

Tracks iterative refinement cycles: render -> analyze -> fix -> re-render.
Each session maintains history of iterations with scores, render paths,
analysis results, and scripts applied.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RefinementIteration:
    """One cycle of the refinement loop."""

    iteration: int
    render_paths: dict[str, str] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    script_applied: str = ""


@dataclass
class RefinementSession:
    """Tracks an entire refinement workflow for one object."""

    session_id: str
    object_name: str
    reference_image: str | None = None
    prompt: str = ""
    iterations: list[RefinementIteration] = field(default_factory=list)
    status: str = "active"  # active, converged, abandoned

    def add_iteration(
        self,
        render_paths: dict[str, str],
        analysis: dict[str, Any],
        score: float,
        script_applied: str = "",
    ) -> RefinementIteration:
        """Record a new iteration."""
        it = RefinementIteration(
            iteration=len(self.iterations),
            render_paths=render_paths,
            analysis=analysis,
            score=score,
            script_applied=script_applied,
        )
        self.iterations.append(it)
        return it

    @property
    def latest_score(self) -> float:
        if self.iterations:
            return self.iterations[-1].score
        return 0.0


class RefinementManager:
    """Manages all active refinement sessions."""

    def __init__(self):
        self._sessions: dict[str, RefinementSession] = {}

    def create_session(
        self,
        object_name: str,
        reference_image: str | None = None,
        prompt: str = "",
    ) -> RefinementSession:
        """Create a new refinement session."""
        session_id = str(uuid.uuid4())[:8]
        session = RefinementSession(
            session_id=session_id,
            object_name=object_name,
            reference_image=reference_image,
            prompt=prompt,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> RefinementSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[RefinementSession]:
        """List all sessions."""
        return list(self._sessions.values())

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False


# Singleton
_refinement_manager: RefinementManager | None = None


def get_refinement_manager() -> RefinementManager:
    global _refinement_manager
    if _refinement_manager is None:
        _refinement_manager = RefinementManager()
    return _refinement_manager
