"""Job queue system for AI generation tasks.

This module provides persistent job tracking, history management,
and async generation queue functionality.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class GenerationJob:
    """Represents an AI generation job."""

    id: str
    backend: str
    prompt: str
    image_path: str | None = None
    status: str = "pending"
    progress: float = 0.0
    result_path: str | None = None
    download_url: str | None = None
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    style: str | None = None
    quality: str = "medium"
    output_format: str = "glb"
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        """Set timestamps if not provided."""
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "backend": self.backend,
            "prompt": self.prompt,
            "image_path": self.image_path,
            "status": self.status,
            "progress": self.progress,
            "result_path": self.result_path,
            "download_url": self.download_url,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "style": self.style,
            "quality": self.quality,
            "output_format": self.output_format,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationJob":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            backend=data["backend"],
            prompt=data["prompt"],
            image_path=data.get("image_path"),
            status=data.get("status", "pending"),
            progress=data.get("progress", 0.0),
            result_path=data.get("result_path"),
            download_url=data.get("download_url"),
            error=data.get("error"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            completed_at=data.get("completed_at"),
            style=data.get("style"),
            quality=data.get("quality", "medium"),
            output_format=data.get("output_format", "glb"),
            metadata=data.get("metadata", {}),
        )

    def is_complete(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in ("completed", "failed", "cancelled", "timeout")

    def is_active(self) -> bool:
        """Check if job is still running."""
        return self.status in ("pending", "queued", "processing", "downloading")


class JobQueue:
    """Manages AI generation job queue with persistence.

    Features:
    - Persistent storage of job history
    - Status tracking and updates
    - Configurable history limit
    - Job filtering and search
    """

    def __init__(
        self,
        history_file: str | Path | None = None,
        history_limit: int = 100,
    ):
        """Initialize the job queue.

        Args:
            history_file: Path to history file. If None, uses default location.
            history_limit: Maximum number of jobs to keep in history.
        """
        self._jobs: dict[str, GenerationJob] = {}
        self._history_limit = history_limit

        if history_file:
            self._history_file = Path(history_file)
        else:
            self._history_file = self._get_default_history_path()

        self._load_history()

    def _get_default_history_path(self) -> Path:
        """Get the default history file path."""
        try:
            import bpy

            user_path = Path(bpy.utils.resource_path("USER"))
            cache_dir = user_path / "mcp_blender_cache" / "ai_models"
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir / "job_history.json"
        except Exception:
            # Fallback for non-Blender environments
            cache_dir = Path.home() / ".cache" / "mcp_blender" / "ai_models"
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir / "job_history.json"

    def _load_history(self) -> None:
        """Load job history from disk."""
        if not self._history_file.exists():
            return

        try:
            with open(self._history_file, "r") as f:
                data = json.load(f)

            for job_data in data.get("jobs", []):
                job = GenerationJob.from_dict(job_data)
                self._jobs[job.id] = job

        except (json.JSONDecodeError, IOError, KeyError) as e:
            # History file corrupted, start fresh
            print(f"Warning: Could not load job history: {e}")
            self._jobs = {}

    def _save_history(self) -> None:
        """Save job history to disk."""
        try:
            # Sort jobs by creation time (newest first) and limit
            sorted_jobs = sorted(
                self._jobs.values(),
                key=lambda j: j.created_at,
                reverse=True,
            )

            # Apply history limit
            if len(sorted_jobs) > self._history_limit:
                # Remove old completed jobs first
                jobs_to_keep = []
                completed_count = 0
                for job in sorted_jobs:
                    if job.is_active():
                        jobs_to_keep.append(job)
                    elif completed_count < self._history_limit:
                        jobs_to_keep.append(job)
                        completed_count += 1
                sorted_jobs = jobs_to_keep
                self._jobs = {j.id: j for j in sorted_jobs}

            data = {
                "version": 1,
                "jobs": [j.to_dict() for j in sorted_jobs],
            }

            # Write atomically
            temp_path = self._history_file.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(self._history_file)

        except IOError as e:
            print(f"Warning: Could not save job history: {e}")

    def create_job(
        self,
        backend: str,
        prompt: str,
        image_path: str | None = None,
        style: str | None = None,
        quality: str = "medium",
        output_format: str = "glb",
        metadata: dict | None = None,
    ) -> GenerationJob:
        """Create a new generation job.

        Args:
            backend: Backend name.
            prompt: Generation prompt.
            image_path: Optional input image path.
            style: Optional style.
            quality: Generation quality.
            output_format: Output format.
            metadata: Optional additional metadata.

        Returns:
            Created GenerationJob.
        """
        job = GenerationJob(
            id=str(uuid.uuid4()),
            backend=backend,
            prompt=prompt,
            image_path=image_path,
            style=style,
            quality=quality,
            output_format=output_format,
            metadata=metadata or {},
        )
        self._jobs[job.id] = job
        self._save_history()
        return job

    def add_job(self, job: GenerationJob) -> str:
        """Add an existing job to the queue.

        Args:
            job: Job to add.

        Returns:
            Job ID.
        """
        self._jobs[job.id] = job
        self._save_history()
        return job.id

    def get_job(self, job_id: str) -> GenerationJob | None:
        """Get a job by ID.

        Args:
            job_id: Job ID.

        Returns:
            Job or None if not found.
        """
        return self._jobs.get(job_id)

    def update_job(
        self,
        job_id: str,
        status: str | None = None,
        progress: float | None = None,
        result_path: str | None = None,
        download_url: str | None = None,
        error: str | None = None,
        **kwargs,
    ) -> GenerationJob | None:
        """Update a job's status.

        Args:
            job_id: Job ID.
            status: New status.
            progress: New progress (0.0-1.0).
            result_path: Path to result file.
            download_url: URL to download result.
            error: Error message.
            **kwargs: Additional fields to update.

        Returns:
            Updated job or None if not found.
        """
        job = self._jobs.get(job_id)
        if not job:
            return None

        job.updated_at = datetime.now().isoformat()

        if status is not None:
            job.status = status
            if status in ("completed", "failed", "cancelled"):
                job.completed_at = job.updated_at
        if progress is not None:
            job.progress = max(0.0, min(1.0, progress))
        if result_path is not None:
            job.result_path = result_path
        if download_url is not None:
            job.download_url = download_url
        if error is not None:
            job.error = error

        # Update metadata
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
            else:
                job.metadata[key] = value

        self._save_history()
        return job

    def delete_job(self, job_id: str) -> bool:
        """Delete a job from the queue.

        Args:
            job_id: Job ID.

        Returns:
            True if deleted, False if not found.
        """
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save_history()
            return True
        return False

    def list_jobs(
        self,
        status: str | list[str] | None = None,
        backend: str | None = None,
        limit: int | None = None,
        include_completed: bool = True,
    ) -> list[GenerationJob]:
        """List jobs with optional filtering.

        Args:
            status: Filter by status (single or list).
            backend: Filter by backend name.
            limit: Maximum number of jobs to return.
            include_completed: Include completed jobs.

        Returns:
            List of matching jobs (newest first).
        """
        jobs = list(self._jobs.values())

        # Filter by status
        if status:
            if isinstance(status, str):
                status = [status]
            jobs = [j for j in jobs if j.status in status]

        # Filter by backend
        if backend:
            jobs = [j for j in jobs if j.backend == backend]

        # Exclude completed if requested
        if not include_completed:
            jobs = [j for j in jobs if j.is_active()]

        # Sort by creation time (newest first)
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        # Apply limit
        if limit:
            jobs = jobs[:limit]

        return jobs

    def get_active_jobs(self) -> list[GenerationJob]:
        """Get all active (non-complete) jobs.

        Returns:
            List of active jobs.
        """
        return [j for j in self._jobs.values() if j.is_active()]

    def get_history(
        self,
        limit: int = 50,
        include_active: bool = False,
    ) -> list[dict[str, Any]]:
        """Get generation history with metadata.

        Args:
            limit: Maximum number of entries.
            include_active: Include active jobs.

        Returns:
            List of job summaries.
        """
        jobs = list(self._jobs.values())

        if not include_active:
            jobs = [j for j in jobs if j.is_complete()]

        jobs.sort(key=lambda j: j.created_at, reverse=True)
        jobs = jobs[:limit]

        return [
            {
                "id": j.id,
                "prompt": j.prompt[:100] + "..." if len(j.prompt) > 100 else j.prompt,
                "backend": j.backend,
                "status": j.status,
                "style": j.style,
                "quality": j.quality,
                "has_result": j.result_path is not None,
                "result_path": j.result_path,
                "created_at": j.created_at,
                "completed_at": j.completed_at,
                "error": j.error,
            }
            for j in jobs
        ]

    def clear_completed(self, older_than_hours: float | None = None) -> int:
        """Clear completed jobs from history.

        Args:
            older_than_hours: Only clear jobs older than this.

        Returns:
            Number of jobs cleared.
        """
        now = datetime.now()
        cleared = 0
        to_delete = []

        for job_id, job in self._jobs.items():
            if not job.is_complete():
                continue

            should_delete = True
            if older_than_hours:
                try:
                    completed = datetime.fromisoformat(job.completed_at or job.created_at)
                    age_hours = (now - completed).total_seconds() / 3600
                    should_delete = age_hours >= older_than_hours
                except (ValueError, TypeError):
                    pass

            if should_delete:
                to_delete.append(job_id)

        for job_id in to_delete:
            del self._jobs[job_id]
            cleared += 1

        if cleared > 0:
            self._save_history()

        return cleared

    def clear_failed(self) -> int:
        """Clear all failed jobs.

        Returns:
            Number of jobs cleared.
        """
        failed_ids = [j.id for j in self._jobs.values() if j.status == "failed"]
        for job_id in failed_ids:
            del self._jobs[job_id]

        if failed_ids:
            self._save_history()

        return len(failed_ids)

    def get_job_by_prompt(self, prompt: str, exact: bool = True) -> GenerationJob | None:
        """Find a job by prompt.

        Args:
            prompt: Prompt to search for.
            exact: If True, match exactly. If False, substring match.

        Returns:
            Matching job or None.
        """
        prompt_lower = prompt.lower()
        for job in self._jobs.values():
            if exact:
                if job.prompt.lower() == prompt_lower:
                    return job
            else:
                if prompt_lower in job.prompt.lower():
                    return job
        return None

    def get_last_job(self, backend: str | None = None) -> GenerationJob | None:
        """Get the most recent job.

        Args:
            backend: Optional backend filter.

        Returns:
            Most recent job or None.
        """
        jobs = list(self._jobs.values())
        if backend:
            jobs = [j for j in jobs if j.backend == backend]

        if not jobs:
            return None

        return max(jobs, key=lambda j: j.created_at)

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics.

        Returns:
            Statistics dictionary.
        """
        jobs = list(self._jobs.values())
        status_counts = {}
        backend_counts = {}

        for job in jobs:
            status_counts[job.status] = status_counts.get(job.status, 0) + 1
            backend_counts[job.backend] = backend_counts.get(job.backend, 0) + 1

        return {
            "total_jobs": len(jobs),
            "active_jobs": len([j for j in jobs if j.is_active()]),
            "completed_jobs": len([j for j in jobs if j.status == "completed"]),
            "failed_jobs": len([j for j in jobs if j.status == "failed"]),
            "by_status": status_counts,
            "by_backend": backend_counts,
            "history_file": str(self._history_file),
        }


# Global job queue instance
_job_queue: JobQueue | None = None


def get_job_queue() -> JobQueue:
    """Get the global job queue instance.

    Returns:
        The singleton JobQueue instance.
    """
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue


def reset_job_queue() -> None:
    """Reset the global job queue (for testing)."""
    global _job_queue
    _job_queue = None
