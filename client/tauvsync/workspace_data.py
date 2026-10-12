"""Project list reconciliation and safe cloud naming rules for TAUV Workspace.

All functions are pure: avoid modifying working copies or rewriting server
history when resolving duplicate display names.
"""
from __future__ import annotations

import re


def next_available_name(name: str, projects: list[dict]) -> str:
    """Reserve a case-insensitive unique display name for a new cloud project.

    Caller fetches fresh project list immediately before submitting the upload.
    Existing projects remain separate; revisions are never implicitly merged.
    """
    name = name.strip()
    existing = {
        str(project.get("name") or "").strip().casefold()
        for project in projects
    }
    if name.casefold() not in existing:
        return name

    suffix = re.search(r"\s*\(\d+\)$", name)
    original = name[:suffix.start()].rstrip() if suffix else name
    for counter in range(1, 10000):
        suffix_text = f" ({counter})"
        candidate = original[:80-len(suffix_text)].rstrip() + suffix_text
        if candidate.casefold() not in existing:
            return candidate
    raise ValueError("Too many projects have this name")


def reconcile_projects(remote: list[dict], local: dict[str, dict]) -> list[dict]:
    """Keep removed local checkouts visible without recreating server projects.

    Removed projects are flagged and can only be opened from preserved local
    files. Never infer that a missing server project should be reuploaded.
    """
    result = [dict(project) for project in remote]
    known = {project["id"] for project in result}
    for pid, record in local.items():
        if pid not in known:
            result.append({
                "id": pid,
                "name": record.get("name") or pid,
                "head_revision": record.get("base_revision", 0),
                "prism_project_id": None,
                "cloud_state": "missing_prism",
                "local_only": True,
            })
    return result


def latest_authors(api, projects: list[dict], cached: dict[tuple[str, int], str]
                   ) -> dict[tuple[str, int], str]:
    """Fetch the revision author only once for each observed head revision."""
    result = dict(cached)
    for project in projects:
        pid = project["id"]
        head = int(project.get("head_revision") or 0)
        key = (pid, head)
        if key in result:
            continue
        author = str(project.get("owner") or "").strip()
        if not project.get("local_only") and project.get("cloud_state", "active") == "active":
            try:
                revisions = api.revisions(pid)
                current = next(
                    (rev for rev in revisions if int(rev["number"]) == head),
                    None,
                )
                if current:
                    author = str(current.get("author") or author).strip()
            except Exception:
                # Avoid preventing project refresh if an individual history is
                # temporarily unavailable. The owner's name remains available.
                pass
        result[key] = author
    return result
