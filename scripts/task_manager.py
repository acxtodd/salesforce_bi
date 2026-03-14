#!/usr/bin/env python3
"""
Task Manager – hierarchy-aware operations for tasks.json

Hierarchy-aware task manager for phase-oriented roadmaps. Supports
integer phase IDs, subtasks, dependencies, and extended status values.

Usage examples:
    python scripts/task_manager.py phases
    python scripts/task_manager.py list [--status pending|in_progress|blocked|review|completed|skipped]
    python scripts/task_manager.py show <task-id>
    python scripts/task_manager.py start <task-id> [--owner name] [--force]
    python scripts/task_manager.py update <task-id> --status blocked --note "Waiting on dependency"
    python scripts/task_manager.py complete <task-id> [--commit <sha>] [--pr <url>]
    python scripts/task_manager.py add-file <task-id> path/to/file.py
    python scripts/task_manager.py add-note <task-id> "Implementation complete"
    python scripts/task_manager.py create --phase 1 --title "New task title" [--owner name]
    python scripts/task_manager.py create --parent 1.1 --title "Subtask title" [--owner name]
    python scripts/task_manager.py delete 99.16 [--force]
    python scripts/task_manager.py create-phase --phase 2 --name "Phase Name" --description "Description" [--status pending]
    python scripts/task_manager.py add-ac <task-id> --ac "Criterion 1" --ac "Criterion 2"
    python scripts/task_manager.py set-depends <task-id> --on 1.1 --on 1.2 [--gate "Gate description"]
    python scripts/task_manager.py my-tasks [--owner name]
    python scripts/task_manager.py promote 99.73 --phase 38 --id 38.4
    python scripts/task_manager.py promote 99.100 --merge-to 39.1 --note "Delivered in Phase 39"
    python scripts/task_manager.py renumber-phase --from-phase 17 --to-phase 18 [--dry-run]
    python scripts/task_manager.py ba-review <task-id>
    python scripts/task_manager.py validate-ac <task-id>
    python scripts/task_manager.py promote 99.73 --phase 38 --id 38.4 --skip-ba-check
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def get_tasks_path(project_root: Path | str | None = None) -> Path:
    """Return the default roadmap task file path.

    For AVIA development work, this manager intentionally targets root-level
    `tasks.json` to avoid conflicts with runtime `.avia/` artifacts.
    """
    root = Path(project_root) if project_root else Path.cwd()
    return root / "tasks.json"


# Valid status values for phase-based roadmap tasks
TASK_STATUSES = {"pending", "in_progress", "blocked", "review", "completed", "skipped"}
PHASE_STATUSES = {"pending", "in_progress", "completed", "running", "rolled_back"}

# Terminal statuses that count as "done" for phase completion
TERMINAL_STATUSES = {"completed", "skipped"}

# Ambiguous AC patterns that validate-ac flags as warnings.
# Each entry: (compiled regex, human-readable description, suggested fix).
_AMBIGUOUS_AC_PATTERNS = [
    (
        re.compile(r"all\s+(?:existing\s+)?tests\s+(?:pass\s+)?unchanged", re.IGNORECASE),
        'Ambiguous "all tests unchanged" without scope qualifier',
        'Use "all unrelated tests pass unchanged" to exclude tests for changed behavior.',
    ),
    (
        re.compile(r"all\s+existing\s+tests\s+pass(?!\s+unchanged)", re.IGNORECASE),
        'Ambiguous "all existing tests pass" without scope qualifier',
        'Specify "all unrelated existing tests pass" to clarify scope.',
    ),
]

# Patterns that indicate the AC is properly scoped (suppress false positives).
_CLEAN_AC_PATTERNS = [
    re.compile(r"all\s+unrelated\s+tests", re.IGNORECASE),
]

# Format-signaling pattern: detects ACs that specify output shape keywords.
# Suppressed only when a code-fenced example is present in the AC text.
_FORMAT_SIGNALING_PATTERN = re.compile(
    r"\b(columns?|tables?|layouts?|formats?|schemas?|shapes?|structures?)\b",
    re.IGNORECASE,
)
_FORMAT_SIGNALING_DESCRIPTION = (
    "Format-sensitive AC without code-fenced output example"
)
_FORMAT_SIGNALING_SUGGESTION = (
    "Add a code-fenced example (triple-backtick block) showing the expected "
    "output format in the AC text."
)


class TaskManager:
    def __init__(self, tasks_file: Optional[Path] = None, auto_normalize: bool = True):
        if tasks_file is not None:
            self.tasks_file = tasks_file
        else:
            self.tasks_file = get_tasks_path(Path(__file__).resolve().parents[1])
        self.auto_normalize = auto_normalize
        self.data = self._load()

    # ------------------------------------------------------------------ helpers

    def _load(self) -> Dict:
        if not self.tasks_file.exists():
            raise FileNotFoundError(f"tasks.json not found at {self.tasks_file}")

        # Optional integrity hooks; local no-op unless implemented.
        self._check_and_warn_integrity()

        return json.loads(self.tasks_file.read_text())

    def _check_and_warn_integrity(self) -> None:
        """Check tasks.json integrity and warn/auto-normalize if violations found.

        Optional integration point for tasks.json integrity checks.
        """
        return

    def _save(self) -> None:
        payload = json.dumps(self.data, indent=2, ensure_ascii=False) + "\n"
        self.tasks_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{self.tasks_file.name}.",
            suffix=".tmp",
            dir=str(self.tasks_file.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.tasks_file)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _task_id_key(self, task_id: str) -> Tuple[int, ...]:
        numbers = [int(n) for n in re.findall(r"\d+", task_id)]
        return tuple(numbers) if numbers else (sys.maxsize,)

    def _task_depth(self, task_id: str) -> int:
        # Phase + top-level task = two numeric components -> depth 0
        depth = max(len(re.findall(r"\d+", task_id)) - 2, 0)
        return depth

    def _resolve_owner(self, owner: Optional[str]) -> str:
        if owner:
            return owner
        try:
            result = subprocess.run(
                ["git", "config", "user.name"],
                capture_output=True,
                text=True,
                check=True,
            )
            resolved = result.stdout.strip()
            if not resolved:
                raise ValueError
            return resolved
        except Exception:
            print("Owner missing. Provide --owner or configure git user.name.")
            sys.exit(1)

    def _find_task_with_phase(self, task_id: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        for phase in self.data.get("phases", []):
            for task in phase.get("tasks", []):
                if task["id"] == task_id:
                    return task, phase
        return None, None

    def _find_task(self, task_id: str) -> Optional[Dict]:
        task, _ = self._find_task_with_phase(task_id)
        return task

    def _find_backlog_item(self, item_id: str) -> Optional[Dict]:
        for item in self.data.get("backlog", []):
            if item.get("id") == item_id:
                return item
        return None

    def _get_phase_by_id(self, phase_id: int) -> Optional[Dict]:
        """Find phase by integer ID."""
        for phase in self.data.get("phases", []):
            if phase["phase"] == phase_id:
                return phase
        return None

    def _phase_index(self, phase_obj: Dict) -> int:
        for idx, phase in enumerate(self.data.get("phases", []), start=1):
            if phase is phase_obj:
                return idx
        return 0

    def _next_index_store(self) -> Dict[str, int]:
        """Return persisted monotonic counters for task-id allocation.

        Keys are task-id prefixes (e.g., ``"99."`` or ``"9.1."``), values are
        the *next* numeric index to allocate for that prefix.
        """
        meta = self.data.setdefault("meta", {})
        counters = meta.setdefault("next_task_index", {})
        normalized: Dict[str, int] = {}
        for key, value in counters.items():
            try:
                normalized[str(key)] = max(1, int(value))
            except (TypeError, ValueError):
                continue
        meta["next_task_index"] = normalized
        return normalized

    def _ensure_prefix_counter(self, prefix: str, siblings: List[Dict]) -> int:
        """Return current next index for *prefix*, initializing from siblings."""
        counters = self._next_index_store()
        current = counters.get(prefix)
        if current is not None:
            return current

        indices: List[int] = []
        for task in siblings:
            numbers = re.findall(r"\d+", str(task.get("id", "")))
            if numbers:
                indices.append(int(numbers[-1]))
        next_index = max(indices) + 1 if indices else 1
        counters[prefix] = next_index
        return next_index

    def _bump_prefix_counter(self, prefix: str, used_index: int) -> None:
        """Ensure next index for *prefix* is strictly greater than *used_index*."""
        counters = self._next_index_store()
        current = counters.get(prefix, 1)
        counters[prefix] = max(current, used_index + 1)

    def _register_existing_task_id(self, task_id: str, phase_number: int, parent: Optional[str]) -> None:
        """Update counters so future allocation never reuses *task_id*."""
        numbers = re.findall(r"\d+", task_id)
        if not numbers:
            return

        used_index = int(numbers[-1])
        if parent:
            prefix = f"{parent}."
            self._bump_prefix_counter(prefix, used_index)
            return

        # Top-level tasks follow "<phase>.<n>".
        if len(numbers) == 2 and int(numbers[0]) == phase_number:
            prefix = f"{phase_number}."
            self._bump_prefix_counter(prefix, used_index)

    def _generate_task_id(self, phase_obj: Dict, parent: Optional[str]) -> str:
        phase_number = str(phase_obj["phase"])

        if parent:
            prefix = f"{parent}."
            siblings = [
                task
                for task in phase_obj.get("tasks", [])
                if task.get("parent") == parent
            ]
        else:
            prefix = f"{phase_number}."
            siblings = [
                task
                for task in phase_obj.get("tasks", [])
                if not task.get("parent")
            ]

        next_index = self._ensure_prefix_counter(prefix, siblings)
        self._bump_prefix_counter(prefix, next_index)
        return prefix + str(next_index)

    def _sort_phase_tasks(self, phase_obj: Dict) -> None:
        phase_obj["tasks"] = sorted(
            phase_obj.get("tasks", []),
            key=lambda t: self._task_id_key(t["id"]),
        )

    def _check_phase_completion(self, phase_id: int) -> bool:
        """Check if all tasks in a phase are terminal and update phase status.

        Args:
            phase_id: Integer phase ID to check.

        Returns:
            True if phase status was updated to 'completed', False otherwise.
        """
        phase = self._get_phase_by_id(phase_id)
        if not phase:
            return False

        # Already completed - idempotent
        if phase.get("status") == "completed":
            return False

        tasks = phase.get("tasks", [])
        if not tasks:
            return False

        # Check if ALL tasks are terminal (completed or skipped)
        for task in tasks:
            if task.get("status", "") not in TERMINAL_STATUSES:
                return False

        # All tasks terminal - update phase status
        phase["status"] = "completed"
        self._save()
        print(f"Phase {phase_id} auto-completed (all tasks terminal)")
        return True

    # ------------------------------------------------------------------ commands

    def create_phase(
        self, phase_id: int, name: str, description: str = "", status: str = "pending"
    ) -> None:
        if self._get_phase_by_id(phase_id):
            print(f"Phase {phase_id} already exists")
            sys.exit(0)

        if status not in PHASE_STATUSES:
            print(f"Invalid phase status. Choose from: {', '.join(sorted(PHASE_STATUSES))}")
            sys.exit(1)

        new_phase = {
            "phase": phase_id,
            "name": name,
            "description": description,
            "status": status,
            "tasks": [],
        }
        self.data.setdefault("phases", []).append(new_phase)
        # Sort phases by ID
        self.data["phases"] = sorted(self.data["phases"], key=lambda p: p["phase"])
        self._save()
        print(f"Created Phase {phase_id}: {name} [{status}]")

    def update_phase(
        self,
        phase_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> None:
        phase = self._get_phase_by_id(phase_id)
        if not phase:
            print(f"Phase {phase_id} not found")
            sys.exit(1)

        if status is not None and status not in PHASE_STATUSES:
            print(
                f"Invalid phase status. Choose from: {', '.join(sorted(PHASE_STATUSES))}"
            )
            sys.exit(1)

        if name is not None:
            phase["name"] = name
        if description is not None:
            phase["description"] = description
        if status is not None:
            phase["status"] = status

        self._save()
        print(
            f"Updated Phase {phase_id}: "
            f"name={phase['name']} status={phase['status']}"
        )

    def list_tasks(self, status: Optional[str] = None) -> None:
        for phase in self.data.get("phases", []):
            tasks = phase.get("tasks", [])
            if status:
                tasks = [t for t in tasks if t.get("status") == status]
            if not tasks:
                continue

            print(f"\nPhase {phase['phase']}: {phase['name']}")
            print("-" * 60)
            for task in sorted(tasks, key=lambda t: self._task_id_key(t["id"])):
                owner = task.get("owner") or "unassigned"
                depth = self._task_depth(task["id"])
                indent = "  " * depth
                status_emoji = {
                    "pending": "   ",
                    "in_progress": ">>>",
                    "blocked": "[X]",
                    "review": "[?]",
                    "completed": "[+]",
                    "skipped": "[-]",
                }.get(task.get("status", "pending"), "   ")
                print(f"{indent}{status_emoji} {task['id']}: {task['title']}")
                print(f"{indent}    Owner: {owner} | Status: {task.get('status', 'pending')}")

    def list_phases(self) -> None:
        for phase in self.data.get("phases", []):
            tasks = phase.get("tasks", [])
            total = len(tasks)
            done = sum(1 for task in tasks if task.get("status") == "completed")
            marker = " <-- active" if phase.get("status") != "completed" and total > 0 else ""
            print(
                f"Phase {phase['phase']}: {phase['name']} — "
                f"{phase.get('status', 'pending')} ({done}/{total} done){marker}"
            )

    def show_task(self, task_id: str) -> None:
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)

        print(f"\nTask: {task['id']}")
        print(f"Title: {task['title']}")
        if task.get("description"):
            print(f"Description: {task['description']}")
        print(f"Status: {task.get('status', 'pending')}")
        print(f"Owner: {task.get('owner') or 'unassigned'}")
        if task.get("parent"):
            print(f"Parent: {task['parent']}")
        print(f"Created: {task.get('createdAt', 'N/A')}")
        print(f"Updated: {task.get('updatedAt', 'N/A')}")
        if task.get("startedAt"):
            print(f"Started: {task['startedAt']}")
        if task.get("completedAt"):
            print(f"Completed: {task['completedAt']}")

        if task.get("depends_on"):
            print(f"\nDepends On: {', '.join(task['depends_on'])}")

        if task.get("acceptance_criteria"):
            print(f"\nAcceptance Criteria ({len(task['acceptance_criteria'])}):")
            for idx, ac in enumerate(task["acceptance_criteria"], 1):
                print(f"  {idx}. {ac}")

        if task.get("files_modified"):
            print(f"\nFiles Modified ({len(task['files_modified'])}):")
            for path in task["files_modified"]:
                print(f"  - {path}")

        if task.get("commits"):
            print(f"\nCommits ({len(task['commits'])}):")
            for sha in task["commits"]:
                print(f"  - {sha}")

        if task.get("pull_requests"):
            print(f"\nPull Requests ({len(task['pull_requests'])}):")
            for pr in task["pull_requests"]:
                print(f"  - {pr}")

        if task.get("progress_notes"):
            print(f"\nProgress Notes ({len(task['progress_notes'])}):")
            for note in task["progress_notes"]:
                print(f"  [{note['timestamp']}] {note['note']}")

    def update_status(self, task_id: str, status: str, note: Optional[str] = None) -> None:
        if status not in TASK_STATUSES:
            print(f"Invalid status. Choose from: {', '.join(sorted(TASK_STATUSES))}")
            sys.exit(1)

        task, phase = self._find_task_with_phase(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)

        previous = task.get("status", "pending")
        task["status"] = status
        task["updatedAt"] = self._now_iso()

        if previous != "in_progress" and status == "in_progress":
            task["startedAt"] = self._now_iso()
        if status == "completed":
            task["completedAt"] = self._now_iso()

        if note:
            task.setdefault("progress_notes", []).append(
                {"timestamp": self._now_iso(), "note": note}
            )

        self._save()
        print(f"Task {task_id} status updated: {previous} -> {status}")
        if note:
            print(f"   Added note: {note}")

        if phase and status in TERMINAL_STATUSES:
            self._check_phase_completion(phase["phase"])

    def start_task(self, task_id: str, owner: Optional[str], force: bool = False) -> None:
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)

        resolved_owner = self._resolve_owner(owner)
        active = []
        for phase in self.data.get("phases", []):
            for existing in phase.get("tasks", []):
                if (
                    existing.get("owner") == resolved_owner
                    and existing.get("status") == "in_progress"
                    and existing["id"] != task_id
                ):
                    active.append(existing["id"])

        if active and not force:
            print(
                f"{resolved_owner} already has in-progress task(s): {', '.join(active)}. "
                "Use --force to override."
            )
            sys.exit(1)
        if active and force:
            print(f"Overriding active task(s): {', '.join(active)}")

        task["status"] = "in_progress"
        task["owner"] = resolved_owner
        task["startedAt"] = self._now_iso()
        task["updatedAt"] = self._now_iso()
        task.setdefault("progress_notes", []).append(
            {"timestamp": self._now_iso(), "note": f"Started by {resolved_owner}"}
        )

        self._save()
        print(f"Task {task_id} started by {resolved_owner}")

    def complete_task(self, task_id: str, commit: Optional[str], pr: Optional[str]) -> None:
        task, phase = self._find_task_with_phase(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)

        task["status"] = "completed"
        task["completedAt"] = self._now_iso()
        task["updatedAt"] = self._now_iso()

        if commit:
            task.setdefault("commits", [])
            if commit not in task["commits"]:
                task["commits"].append(commit)

        if pr:
            task.setdefault("pull_requests", [])
            if pr not in task["pull_requests"]:
                task["pull_requests"].append(pr)

        note_bits = ["Task completed"]
        if commit:
            note_bits.append(f"commit: {commit[:8]}")
        if pr:
            note_bits.append(f"PR: {pr}")
        task.setdefault("progress_notes", []).append(
            {"timestamp": self._now_iso(), "note": ", ".join(note_bits)}
        )

        self._save()
        print(f"Task {task_id} marked as completed")

        if phase:
            self._check_phase_completion(phase["phase"])

    def delete_task(self, task_id: str, force: bool = False) -> None:
        """Delete a task by ID.

        By default, deletion is conservative:
        - Reject if the task has subtasks.
        - Reject if other tasks depend on this task.

        With ``--force``:
        - Delete the task and all descendant subtasks in the same phase.
        - Remove deleted IDs from other tasks' ``depends_on`` lists.
        """
        task, phase = self._find_task_with_phase(task_id)
        if not task or not phase:
            print(f"Task {task_id} not found")
            sys.exit(1)

        phase_tasks = phase.get("tasks", [])
        subtasks = [t for t in phase_tasks if t.get("parent") == task_id]
        dependents = [
            t
            for p in self.data.get("phases", [])
            for t in p.get("tasks", [])
            if task_id in t.get("depends_on", [])
        ]

        if subtasks and not force:
            subtask_ids = ", ".join(sorted(t["id"] for t in subtasks))
            print(
                f"Task {task_id} has subtasks: {subtask_ids}. "
                "Use --force to delete task + descendants."
            )
            sys.exit(1)

        if dependents and not force:
            dependent_ids = ", ".join(sorted(t["id"] for t in dependents))
            print(
                f"Task {task_id} is referenced by depends_on in: {dependent_ids}. "
                "Use --force to delete and scrub dependencies."
            )
            sys.exit(1)

        delete_ids = {task_id}
        if force:
            pending_parents = {task_id}
            while pending_parents:
                parent_id = pending_parents.pop()
                children = [
                    t["id"] for t in phase_tasks if t.get("parent") == parent_id
                ]
                for child_id in children:
                    if child_id not in delete_ids:
                        delete_ids.add(child_id)
                        pending_parents.add(child_id)

        for p in self.data.get("phases", []):
            existing = p.get("tasks", [])
            kept = [t for t in existing if t.get("id") not in delete_ids]
            p["tasks"] = kept

        scrubbed_dependencies = 0
        if force:
            for p in self.data.get("phases", []):
                for candidate in p.get("tasks", []):
                    deps = candidate.get("depends_on", [])
                    if not deps:
                        continue
                    new_deps = [dep for dep in deps if dep not in delete_ids]
                    if len(new_deps) != len(deps):
                        candidate["depends_on"] = new_deps
                        candidate["updatedAt"] = self._now_iso()
                        scrubbed_dependencies += 1

        self._save()

        deleted_text = ", ".join(sorted(delete_ids, key=self._task_id_key))
        print(f"Deleted task(s): {deleted_text}")
        if scrubbed_dependencies:
            print(f"Scrubbed depends_on in {scrubbed_dependencies} task(s)")

    def add_file(self, task_id: str, file_path: str) -> None:
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        task.setdefault("files_modified", [])
        if file_path not in task["files_modified"]:
            task["files_modified"].append(file_path)
            task["updatedAt"] = self._now_iso()
            self._save()
            print(f"Added file to {task_id}: {file_path}")
        else:
            print(f"File already tracked: {file_path}")

    def add_note(self, task_id: str, note: str) -> None:
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        task.setdefault("progress_notes", []).append(
            {"timestamp": self._now_iso(), "note": note}
        )
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"Added note to {task_id}")

    def set_description(self, task_id: str, description: str) -> None:
        """Set or update the description for a task.

        Args:
            task_id: The task ID (e.g., "1.1", "2.3").
            description: The new description text.
        """
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        if not description or not description.strip():
            print("Description cannot be empty")
            sys.exit(1)
        task["description"] = description.strip()
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"Updated description for task {task_id}")

    def set_technical_context(self, task_id: str, technical_context: str) -> None:
        """Set or update the technical context for a task.

        Args:
            task_id: The task ID (e.g., "1.1", "2.3").
            technical_context: The new technical context text.
        """
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        if not technical_context or not technical_context.strip():
            print("Technical context cannot be empty")
            sys.exit(1)
        task["technical_context"] = technical_context.strip()
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"Updated technical context for task {task_id}")

    def set_title(self, task_id: str, title: str) -> None:
        """Set or update the title for a task.

        Args:
            task_id: The task ID (e.g., "1.1", "2.3").
            title: The new title text.
        """
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        if not title or not title.strip():
            print("Title cannot be empty")
            sys.exit(1)
        old_title = task.get("title", "")
        task["title"] = title.strip()
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"Updated title for task {task_id}: '{old_title}' -> '{title.strip()}'")

    def add_acceptance_criteria(self, task_id: str, ac_list: List[str]) -> None:
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        task.setdefault("acceptance_criteria", [])
        added = 0
        for ac in ac_list:
            if ac and ac not in task["acceptance_criteria"]:
                task["acceptance_criteria"].append(ac)
                added += 1
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"Added {added} acceptance criteria to {task_id}")

    def clear_acceptance_criteria(self, task_id: str) -> None:
        """Clear all acceptance criteria for a task.

        Args:
            task_id: The task ID (e.g., "1.1", "2.3").
        """
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        count = len(task.get("acceptance_criteria", []))
        task["acceptance_criteria"] = []
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"Cleared {count} acceptance criteria from {task_id}")

    def add_reference(self, task_id: str, ref_list: List[str]) -> None:
        """Add reference file paths to a task.

        Args:
            task_id: The task ID (e.g., "1.1", "2.3").
            ref_list: List of file paths to add as references.
        """
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        task.setdefault("references", [])
        added = 0
        for ref in ref_list:
            if ref and ref not in task["references"]:
                task["references"].append(ref)
                added += 1
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"Added {added} references to {task_id}")

    def clear_references(self, task_id: str) -> None:
        """Clear all references for a task.

        Args:
            task_id: The task ID (e.g., "1.1", "2.3").
        """
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        count = len(task.get("references", []))
        task["references"] = []
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"Cleared {count} references from {task_id}")

    def clear_depends_on(self, task_id: str) -> None:
        """Clear all dependencies for a task.

        Args:
            task_id: The task ID (e.g., "1.1", "2.3").
        """
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        old_deps = task.get("depends_on", [])
        task["depends_on"] = []
        task["updatedAt"] = self._now_iso()
        self._save()
        if old_deps:
            print(f"Cleared dependencies from {task_id}: was [{', '.join(old_deps)}]")
        else:
            print(f"{task_id} had no dependencies")

    def set_depends_on(self, task_id: str, depends_on: List[str], gate_criteria: Optional[str]) -> None:
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)
        missing = [dep for dep in depends_on if not self._find_task(dep)]
        if missing:
            print(f"Dependency not found: {', '.join(missing)}")
            sys.exit(1)
        task["depends_on"] = depends_on
        if gate_criteria:
            task["gate_criteria"] = gate_criteria
        task["updatedAt"] = self._now_iso()
        self._save()
        print(f"{task_id} now depends on: {', '.join(depends_on)}")

    def create_task(
        self,
        title: str,
        owner: Optional[str],
        phase_id: Optional[int],
        parent: Optional[str],
        description: Optional[str] = None,
        technical_context: Optional[str] = None,
    ) -> None:
        resolved_owner = self._resolve_owner(owner)

        if parent:
            parent_task, parent_phase = self._find_task_with_phase(parent)
            if not parent_task or not parent_phase:
                print(f"Parent task {parent} not found")
                sys.exit(1)
            phase_obj = parent_phase
        else:
            if phase_id is None:
                print("Top-level tasks require --phase")
                sys.exit(1)
            phase_obj = self._get_phase_by_id(phase_id)
            if not phase_obj:
                print(f"Phase {phase_id} not found")
                sys.exit(1)

        new_id = self._generate_task_id(phase_obj, parent)
        task = {
            "id": new_id,
            "title": title,
            "status": "pending",
            "owner": resolved_owner,
            "createdAt": self._now_iso(),
            "updatedAt": self._now_iso(),
            "files_modified": [],
            "commits": [],
            "pull_requests": [],
            "progress_notes": [],
        }
        if description:
            task["description"] = description
        if technical_context:
            task["technical_context"] = technical_context
        if parent:
            task["parent"] = parent

        phase_obj.setdefault("tasks", []).append(task)
        self._sort_phase_tasks(phase_obj)
        self._save()
        print(f"Created task {new_id}: {title}")

    def my_tasks(self, owner: Optional[str]) -> None:
        resolved_owner = self._resolve_owner(owner)
        print(f"\nTasks for: {resolved_owner}")
        print("=" * 60)

        found = False
        for phase in self.data.get("phases", []):
            owned = [t for t in phase.get("tasks", []) if t.get("owner") == resolved_owner]
            if not owned:
                continue
            found = True
            print(f"\nPhase {phase['phase']}: {phase['name']}")
            print("-" * 60)
            for task in sorted(owned, key=lambda t: self._task_id_key(t["id"])):
                depth = self._task_depth(task["id"])
                indent = "  " * depth
                status_emoji = {
                    "pending": "   ",
                    "in_progress": ">>>",
                    "blocked": "[X]",
                    "review": "[?]",
                    "completed": "[+]",
                    "skipped": "[-]",
                }.get(task.get("status", "pending"), "   ")
                print(f"{indent}{status_emoji} {task['id']}: {task['title']}")
                print(f"{indent}    Status: {task.get('status', 'pending')}")

        if not found:
            print("No tasks found.")

    def next_task(self, owner: Optional[str] = None) -> None:
        """Show the next actionable task."""
        for phase in self.data.get("phases", []):
            if phase.get("status") not in ("pending", "in_progress", "running"):
                continue
            for task in sorted(phase.get("tasks", []), key=lambda t: self._task_id_key(t["id"])):
                if task.get("status") == "pending":
                    # Check dependencies
                    deps = task.get("depends_on", [])
                    blocked = False
                    for dep_id in deps:
                        dep_task = self._find_task(dep_id)
                        if dep_task and dep_task.get("status") != "completed":
                            blocked = True
                            break
                    if not blocked:
                        print(f"\nNext task: {task['id']}")
                        print(f"Title: {task['title']}")
                        if task.get("description"):
                            print(f"Description: {task['description']}")
                        if task.get("acceptance_criteria"):
                            print(f"\nAcceptance Criteria:")
                            for idx, ac in enumerate(task["acceptance_criteria"], 1):
                                print(f"  {idx}. {ac}")
                        return
        print("No pending tasks found.")

    def update_backlog(
        self,
        item_id: str,
        status: str,
        note: Optional[str] = None,
        owner: Optional[str] = None,
        commit: Optional[str] = None,
        pr: Optional[str] = None,
    ) -> None:
        if status not in TASK_STATUSES:
            print(f"Invalid status. Choose from: {', '.join(sorted(TASK_STATUSES))}")
            sys.exit(1)

        item = self._find_backlog_item(item_id)
        if not item:
            print(f"Backlog item {item_id} not found")
            sys.exit(1)

        item["status"] = status
        item["updatedAt"] = self._now_iso()

        if owner:
            item["owner"] = owner

        if note:
            list_key = "progress_notes" if "progress_notes" in item else "notes"
            item.setdefault(list_key, []).append({"timestamp": self._now_iso(), "note": note})

        if commit:
            item.setdefault("commits", [])
            if commit not in item["commits"]:
                item["commits"].append(commit)

        if pr:
            item.setdefault("pull_requests", [])
            if pr not in item["pull_requests"]:
                item["pull_requests"].append(pr)

        self._save()
        print(f"Updated backlog item {item_id}: {status}")


    def ba_review_task(self, task_id: str) -> None:
        """Mark a task as BA-reviewed. Idempotent -- safe to call twice."""
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)

        if task.get("ba_reviewed", False):
            print(f"Task {task_id} already marked as BA-reviewed")
            return

        task["ba_reviewed"] = True
        task["updatedAt"] = self._now_iso()
        task.setdefault("progress_notes", []).append(
            {"timestamp": self._now_iso(), "note": "BA review completed"}
        )
        self._save()
        print(f"Task {task_id} marked as BA-reviewed")

    def validate_ac(self, task_id: str) -> None:
        """Scan acceptance criteria for known-ambiguous patterns (advisory).

        Always exits 0. Prints warnings for matched patterns with suggested
        rewording.
        """
        task = self._find_task(task_id)
        if not task:
            print(f"Task {task_id} not found")
            sys.exit(1)

        acs = task.get("acceptance_criteria", [])
        if not acs:
            print(f"Task {task_id} has no acceptance criteria -- nothing to validate.")
            return

        warnings_found = 0
        for idx, ac in enumerate(acs, 1):
            is_clean_ac = any(clean.search(ac) for clean in _CLEAN_AC_PATTERNS)
            if not is_clean_ac:
                for pattern, description_text, suggestion in _AMBIGUOUS_AC_PATTERNS:
                    if pattern.search(ac):
                        warnings_found += 1
                        print(f"  WARNING AC {idx}: {description_text}")
                        print(f'    Found: "{ac}"')
                        print(f"    Suggestion: {suggestion}")

            # Format-signaling check with code-fence suppression
            if _FORMAT_SIGNALING_PATTERN.search(ac):
                has_ac_example = "```" in ac
                if not has_ac_example:
                    warnings_found += 1
                    print(f"  WARNING AC {idx}: {_FORMAT_SIGNALING_DESCRIPTION}")
                    print(f'    Found: "{ac}"')
                    print(f"    Suggestion: {_FORMAT_SIGNALING_SUGGESTION}")

        if warnings_found == 0:
            print(f"No ambiguous patterns found in {task_id} acceptance criteria.")

    def promote_task(
        self,
        source_id: str,
        phase_id: Optional[int],
        new_id: Optional[str],
        parent: Optional[str],
        owner: Optional[str],
        status: Optional[str],
        note: Optional[str],
        merge_to: Optional[str],
        *,
        skip_ba_check: bool = False,
    ) -> None:
        """Promote a task into a phase with a new ID (no duplicates).

        Moves a task (typically from Phase 99 backlog) into a target phase and
        assigns a new task ID. Source task is removed from its original phase.

        If --merge-to is provided, the source task is removed and a note is
        appended to the existing target task instead of creating a new task.
        """
        source_task, source_phase = self._find_task_with_phase(source_id)
        if not source_task or not source_phase:
            print(f"Source task {source_id} not found")
            sys.exit(1)

        # Merge-only path: add note to existing task and remove source
        if merge_to:
            target_task = self._find_task(merge_to)
            if not target_task:
                print(f"Merge target task {merge_to} not found")
                sys.exit(1)

            # BA review gate for merge target (phase task keeps the AC after merge).
            target_acs = target_task.get("acceptance_criteria", [])
            if target_acs and not target_task.get("ba_reviewed", False):
                if skip_ba_check:
                    print(
                        f"WARNING: Skipping BA review check for merge target {merge_to} "
                        f"(--skip-ba-check). Task has {len(target_acs)} "
                        "unreviewed acceptance criteria."
                    )
                else:
                    print(
                        f"BA review required: merge target task {merge_to} has "
                        f"{len(target_acs)} acceptance criteria but ba_reviewed is not set. "
                        f"Run 'ba-review {merge_to}' first, or use --skip-ba-check to bypass."
                    )
                    sys.exit(1)

            target_task.setdefault("progress_notes", []).append(
                {
                    "timestamp": self._now_iso(),
                    "note": f"Promoted from {source_id}"
                    + (f" ({note})" if note else ""),
                }
            )
            target_task["updatedAt"] = self._now_iso()
            source_phase["tasks"] = [
                t for t in source_phase.get("tasks", []) if t.get("id") != source_id
            ]
            self._save()
            print(f"Promoted {source_id} into existing task {merge_to} (source removed)")
            return

        # BA review gate for direct source promotion into a new task.
        acs = source_task.get("acceptance_criteria", [])
        if acs and not source_task.get("ba_reviewed", False):
            if skip_ba_check:
                print(
                    f"WARNING: Skipping BA review check for {source_id} "
                    f"(--skip-ba-check). Task has {len(acs)} unreviewed acceptance criteria."
                )
            else:
                print(
                    f"BA review required: source task {source_id} has "
                    f"{len(acs)} acceptance criteria "
                    f"but ba_reviewed is not set. Run 'ba-review {source_id}' first, "
                    f"or use --skip-ba-check to bypass."
                )
                sys.exit(1)

        if phase_id is None:
            print("Promote requires --phase unless --merge-to is used")
            sys.exit(1)

        phase_obj = self._get_phase_by_id(phase_id)
        if not phase_obj:
            print(f"Phase {phase_id} not found")
            sys.exit(1)

        if parent:
            parent_task, parent_phase = self._find_task_with_phase(parent)
            if not parent_task or not parent_phase:
                print(f"Parent task {parent} not found")
                sys.exit(1)
            if parent_phase.get("phase") != phase_id:
                print(f"Parent task {parent} is not in Phase {phase_id}")
                sys.exit(1)

        if new_id:
            if self._find_task(new_id):
                print(f"Target task ID {new_id} already exists")
                sys.exit(1)
            target_id = new_id
        else:
            target_id = self._generate_task_id(phase_obj, parent)

        if status and status not in TASK_STATUSES:
            print(f"Invalid status. Choose from: {', '.join(sorted(TASK_STATUSES))}")
            sys.exit(1)

        # Normalize notes to progress_notes
        progress_notes = list(source_task.get("progress_notes", []))
        if source_task.get("notes"):
            progress_notes.extend(source_task.get("notes", []))

        progress_notes.append(
            {
                "timestamp": self._now_iso(),
                "note": f"Promoted from {source_id}"
                + (f" ({note})" if note else ""),
            }
        )

        new_task = dict(source_task)
        new_task["id"] = target_id
        if parent:
            new_task["parent"] = parent
        else:
            new_task.pop("parent", None)
        if owner:
            new_task["owner"] = owner
        new_task["status"] = status or "pending"
        new_task["updatedAt"] = self._now_iso()
        new_task["progress_notes"] = progress_notes

        # Clear lifecycle fields unless explicitly completed
        if new_task["status"] != "completed":
            new_task.pop("completedAt", None)
        if new_task["status"] == "pending":
            new_task.pop("startedAt", None)

        # Ensure standard arrays exist
        new_task.setdefault("files_modified", [])
        new_task.setdefault("commits", [])
        new_task.setdefault("pull_requests", [])
        new_task.setdefault("acceptance_criteria", [])

        phase_obj.setdefault("tasks", []).append(new_task)
        self._sort_phase_tasks(phase_obj)
        self._register_existing_task_id(target_id, phase_id, parent)
        self._register_existing_task_id(
            source_id,
            int(source_phase.get("phase", 0)),
            source_task.get("parent"),
        )

        source_phase["tasks"] = [
            t for t in source_phase.get("tasks", []) if t.get("id") != source_id
        ]

        self._save()
        print(f"Promoted {source_id} -> {target_id} in Phase {phase_id}")

    def renumber_phase(self, from_phase: int, to_phase: int, dry_run: bool = False) -> None:
        """Renumber a phase and all task IDs that belong to it.

        Also rewrites structural references:
        - ``depends_on`` entries across all tasks
        - ``parent`` pointers
        - ``meta.next_task_index`` prefixes
        """
        if from_phase == to_phase:
            print("--from-phase and --to-phase must differ")
            sys.exit(1)

        phase_obj = self._get_phase_by_id(from_phase)
        if not phase_obj:
            print(f"Phase {from_phase} not found")
            sys.exit(1)
        if self._get_phase_by_id(to_phase):
            print(f"Target phase {to_phase} already exists")
            sys.exit(1)

        old_prefix = f"{from_phase}."
        new_prefix = f"{to_phase}."

        id_map: Dict[str, str] = {}
        for task in phase_obj.get("tasks", []):
            old_id = task.get("id")
            if not isinstance(old_id, str) or not old_id.startswith(old_prefix):
                print(
                    f"Task ID {old_id!r} in Phase {from_phase} does not start with {old_prefix!r}; "
                    "aborting to avoid unsafe rewrite."
                )
                sys.exit(1)
            new_id = new_prefix + old_id[len(old_prefix):]
            if new_id in id_map.values():
                print(f"Renumber collision within phase: {new_id}")
                sys.exit(1)
            id_map[old_id] = new_id

        external_ids = {
            str(task.get("id"))
            for phase in self.data.get("phases", [])
            if phase is not phase_obj
            for task in phase.get("tasks", [])
            if task.get("id") is not None
        }
        collisions = sorted(
            new_id for new_id in id_map.values() if new_id in external_ids
        )
        if collisions:
            print(
                "Renumber would collide with existing task IDs: "
                + ", ".join(collisions)
            )
            sys.exit(1)

        counters = self._next_index_store()
        counter_map: Dict[str, str] = {
            key: new_prefix + key[len(old_prefix):]
            for key in list(counters.keys())
            if key.startswith(old_prefix)
        }

        dependency_changes = 0
        parent_changes = 0
        for phase in self.data.get("phases", []):
            for task in phase.get("tasks", []):
                parent = task.get("parent")
                if parent in id_map:
                    parent_changes += 1
                deps = task.get("depends_on", [])
                dependency_changes += sum(1 for dep in deps if dep in id_map)

        if dry_run:
            print(
                f"Dry run: renumber Phase {from_phase} -> {to_phase} "
                f"({len(id_map)} task IDs)"
            )
            for old_id in sorted(id_map.keys(), key=self._task_id_key):
                print(f"  {old_id} -> {id_map[old_id]}")
            if counter_map:
                print("Counter key rewrites:")
                for old_key in sorted(counter_map):
                    print(f"  {old_key} -> {counter_map[old_key]}")
            print(
                "Reference rewrites: "
                f"depends_on={dependency_changes}, parent={parent_changes}"
            )
            return

        for task in phase_obj.get("tasks", []):
            old_id = str(task["id"])
            task["id"] = id_map[old_id]

        for phase in self.data.get("phases", []):
            for task in phase.get("tasks", []):
                parent = task.get("parent")
                if parent in id_map:
                    task["parent"] = id_map[parent]
                    task["updatedAt"] = self._now_iso()

                deps = task.get("depends_on", [])
                if deps:
                    new_deps = [id_map.get(dep, dep) for dep in deps]
                    if new_deps != deps:
                        task["depends_on"] = new_deps
                        task["updatedAt"] = self._now_iso()

        if counter_map:
            remapped_values: Dict[str, int] = {}
            for old_key, new_key in counter_map.items():
                value = counters.get(old_key, 1)
                remapped_values[new_key] = max(remapped_values.get(new_key, 1), value)
            for old_key in counter_map:
                counters.pop(old_key, None)
            for new_key, value in remapped_values.items():
                counters[new_key] = max(counters.get(new_key, 1), value)

        phase_obj["phase"] = to_phase
        self._sort_phase_tasks(phase_obj)
        self.data["phases"] = sorted(self.data.get("phases", []), key=lambda p: p["phase"])
        self._save()
        print(
            f"Renumbered Phase {from_phase} -> {to_phase}; "
            f"updated {len(id_map)} task IDs, "
            f"{dependency_changes} depends_on refs, {parent_changes} parent refs."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="AVIA Task Manager for roadmap tasks.json")
    parser.add_argument("--file", "-f", type=Path, help="Path to tasks.json")
    subparsers = parser.add_subparsers(dest="command")

    # list
    subparsers.add_parser("phases", help="List phase summary")

    # list
    list_parser = subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument(
        "--status",
        choices=["pending", "in_progress", "blocked", "review", "completed", "skipped"],
    )

    # show
    show_parser = subparsers.add_parser("show", help="Show task details")
    show_parser.add_argument("task_id")

    # update
    update_parser = subparsers.add_parser("update", help="Update task status")
    update_parser.add_argument("task_id")
    update_parser.add_argument(
        "--status",
        required=True,
        choices=["pending", "in_progress", "blocked", "review", "completed", "skipped"],
    )
    update_parser.add_argument("--note")

    # start
    start_parser = subparsers.add_parser("start", help="Start a task")
    start_parser.add_argument("task_id")
    start_parser.add_argument("--owner", help="Defaults to git user.name")
    start_parser.add_argument(
        "--force", action="store_true", help="Allow multiple in-progress tasks for the owner"
    )

    # complete
    complete_parser = subparsers.add_parser("complete", help="Complete a task")
    complete_parser.add_argument("task_id")
    complete_parser.add_argument("--commit")
    complete_parser.add_argument("--pr")

    # delete
    delete_parser = subparsers.add_parser("delete", help="Delete a task")
    delete_parser.add_argument("task_id")
    delete_parser.add_argument(
        "--force",
        action="store_true",
        help="Delete task descendants and scrub depends_on references",
    )

    # add-file
    add_file_parser = subparsers.add_parser("add-file", help="Track modified file")
    add_file_parser.add_argument("task_id")
    add_file_parser.add_argument("file_path")

    # add-note
    add_note_parser = subparsers.add_parser("add-note", help="Add progress note")
    add_note_parser.add_argument("task_id")
    add_note_parser.add_argument("note")

    # set-description
    set_desc_parser = subparsers.add_parser("set-description", help="Set task description")
    set_desc_parser.add_argument("task_id", help="Task ID (e.g., 1.1)")
    set_desc_parser.add_argument("description", help="New description text")

    # set-technical-context
    set_tc_parser = subparsers.add_parser(
        "set-technical-context", help="Set task technical context"
    )
    set_tc_parser.add_argument("task_id", help="Task ID (e.g., 1.1)")
    set_tc_parser.add_argument("technical_context", help="New technical context text")

    # set-title
    set_title_parser = subparsers.add_parser("set-title", help="Set task title")
    set_title_parser.add_argument("task_id", help="Task ID (e.g., 1.1)")
    set_title_parser.add_argument("title", help="New title text")

    # create
    create_parser = subparsers.add_parser("create", help="Create a new task")
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--description")
    create_parser.add_argument("--owner", help="Defaults to git user.name")
    create_parser.add_argument("--phase", type=int, help="Phase ID (required for top-level tasks)")
    create_parser.add_argument("--parent", help="Parent task ID for subtasks")
    create_parser.add_argument("--technical-context", help="BA-authored integration guidance for the coder agent")

    # create-phase
    create_phase_parser = subparsers.add_parser("create-phase", help="Create a new phase")
    create_phase_parser.add_argument("--phase", type=int, required=True, help="Phase ID (integer)")
    create_phase_parser.add_argument("--name", required=True, help="Phase name")
    create_phase_parser.add_argument("--description", default="")
    create_phase_parser.add_argument(
        "--status",
        choices=["pending", "in_progress", "completed", "running", "rolled_back"],
        default="pending",
    )

    # update-phase
    update_phase_parser = subparsers.add_parser("update-phase", help="Update an existing phase")
    update_phase_parser.add_argument("--phase", type=int, required=True, help="Phase ID (integer)")
    update_phase_parser.add_argument("--name", help="New phase name")
    update_phase_parser.add_argument("--description", help="New phase description")
    update_phase_parser.add_argument(
        "--status",
        choices=["pending", "in_progress", "completed", "running", "rolled_back"],
    )

    # my-tasks
    my_parser = subparsers.add_parser("my-tasks", help="Show tasks for an owner")
    my_parser.add_argument("--owner", help="Defaults to git user.name")

    # add-ac
    ac_parser = subparsers.add_parser("add-ac", help="Add acceptance criteria")
    ac_parser.add_argument("task_id")
    ac_parser.add_argument("--ac", action="append", required=True)

    # clear-ac
    clear_ac_parser = subparsers.add_parser("clear-ac", help="Clear all acceptance criteria")
    clear_ac_parser.add_argument("task_id")

    # add-ref
    add_ref_parser = subparsers.add_parser("add-ref", help="Add reference file paths")
    add_ref_parser.add_argument("task_id")
    add_ref_parser.add_argument("--ref", action="append", required=True)

    # clear-refs
    clear_refs_parser = subparsers.add_parser("clear-refs", help="Clear all references")
    clear_refs_parser.add_argument("task_id")

    # set-depends
    dep_parser = subparsers.add_parser("set-depends", help="Set dependencies")
    dep_parser.add_argument("task_id")
    dep_parser.add_argument("--on", action="append", required=True, help="Task ID this depends on")
    dep_parser.add_argument("--gate", help="Gate criteria text")

    # clear-depends
    clear_dep_parser = subparsers.add_parser("clear-depends", help="Clear all dependencies")
    clear_dep_parser.add_argument("task_id")

    # next
    next_parser = subparsers.add_parser("next", help="Show next actionable task")
    next_parser.add_argument("--owner", help="Filter by owner")

    # backlog-update
    backlog_parser = subparsers.add_parser("backlog-update", help="Update backlog item status")
    backlog_parser.add_argument("item_id", help="Backlog item ID (e.g., B-003)")
    backlog_parser.add_argument(
        "--status",
        required=True,
        choices=["pending", "in_progress", "blocked", "review", "completed", "skipped"],
    )
    backlog_parser.add_argument("--note")
    backlog_parser.add_argument("--owner")
    backlog_parser.add_argument("--commit")
    backlog_parser.add_argument("--pr")

    # promote
    promote_parser = subparsers.add_parser(
        "promote",
        help="Promote a task into a phase (renumber without duplicates)",
    )
    promote_parser.add_argument("source_id", help="Source task ID (e.g., 99.73)")
    promote_parser.add_argument("--phase", type=int, help="Target phase ID (integer)")
    promote_parser.add_argument("--id", dest="new_id", help="New task ID (e.g., 38.4)")
    promote_parser.add_argument(
        "--parent",
        help="Optional parent task ID in target phase (creates subtask under parent)",
    )
    promote_parser.add_argument("--owner", help="Override owner for new task")
    promote_parser.add_argument(
        "--status",
        choices=["pending", "in_progress", "blocked", "review", "completed", "skipped"],
        help="Status for new task (default: pending)",
    )
    promote_parser.add_argument("--note", help="Promotion note to append")
    promote_parser.add_argument(
        "--merge-to",
        dest="merge_to",
        help="Merge into existing task ID (removes source without creating new task)",
    )
    promote_parser.add_argument(
        "--skip-ba-check",
        action="store_true",
        help="Bypass BA review gate on source/merge-target task (prints advisory warning)",
    )

    # renumber-phase
    renumber_parser = subparsers.add_parser(
        "renumber-phase",
        help="Renumber a phase and rewrite task IDs/dependencies safely",
    )
    renumber_parser.add_argument(
        "--from-phase",
        type=int,
        required=True,
        help="Existing phase ID to rename",
    )
    renumber_parser.add_argument(
        "--to-phase",
        type=int,
        required=True,
        help="New phase ID",
    )
    renumber_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview ID/reference rewrites without writing tasks.json",
    )
    # ba-review
    ba_review_parser = subparsers.add_parser(
        "ba-review",
        help="Mark a task as BA-reviewed (sets ba_reviewed: true)",
    )
    ba_review_parser.add_argument("task_id", help="Task ID to mark as reviewed")

    # validate-ac
    validate_ac_parser = subparsers.add_parser(
        "validate-ac",
        help="Scan acceptance criteria for ambiguous patterns (advisory, exits 0)",
    )
    validate_ac_parser.add_argument("task_id", help="Task ID to validate")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    tm = TaskManager(args.file)

    if args.command == "phases":
        tm.list_phases()
    elif args.command == "list":
        tm.list_tasks(args.status)
    elif args.command == "show":
        tm.show_task(args.task_id)
    elif args.command == "update":
        tm.update_status(args.task_id, args.status, args.note)
    elif args.command == "start":
        tm.start_task(args.task_id, args.owner, args.force)
    elif args.command == "complete":
        tm.complete_task(args.task_id, args.commit, args.pr)
    elif args.command == "delete":
        tm.delete_task(args.task_id, args.force)
    elif args.command == "add-file":
        tm.add_file(args.task_id, args.file_path)
    elif args.command == "add-note":
        tm.add_note(args.task_id, args.note)
    elif args.command == "set-description":
        tm.set_description(args.task_id, args.description)
    elif args.command == "set-technical-context":
        tm.set_technical_context(args.task_id, args.technical_context)
    elif args.command == "set-title":
        tm.set_title(args.task_id, args.title)
    elif args.command == "create":
        tm.create_task(args.title, args.owner, args.phase, args.parent, args.description, getattr(args, 'technical_context', None))
    elif args.command == "create-phase":
        tm.create_phase(args.phase, args.name, args.description, args.status)
    elif args.command == "update-phase":
        tm.update_phase(
            args.phase,
            name=args.name,
            description=args.description,
            status=args.status,
        )
    elif args.command == "my-tasks":
        tm.my_tasks(args.owner)
    elif args.command == "add-ac":
        tm.add_acceptance_criteria(args.task_id, args.ac)
    elif args.command == "clear-ac":
        tm.clear_acceptance_criteria(args.task_id)
    elif args.command == "add-ref":
        tm.add_reference(args.task_id, args.ref)
    elif args.command == "clear-refs":
        tm.clear_references(args.task_id)
    elif args.command == "set-depends":
        tm.set_depends_on(args.task_id, args.on, args.gate)
    elif args.command == "clear-depends":
        tm.clear_depends_on(args.task_id)
    elif args.command == "next":
        tm.next_task(args.owner)
    elif args.command == "backlog-update":
        tm.update_backlog(args.item_id, args.status, args.note, args.owner, args.commit, args.pr)
    elif args.command == "promote":
        tm.promote_task(
            args.source_id,
            args.phase,
            args.new_id,
            args.parent,
            args.owner,
            args.status,
            args.note,
            args.merge_to,
            skip_ba_check=args.skip_ba_check,
        )
    elif args.command == "renumber-phase":
        tm.renumber_phase(args.from_phase, args.to_phase, args.dry_run)
    elif args.command == "ba-review":
        tm.ba_review_task(args.task_id)
    elif args.command == "validate-ac":
        tm.validate_ac(args.task_id)


if __name__ == "__main__":
    main()
