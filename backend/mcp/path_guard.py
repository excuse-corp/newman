from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from backend.tools.workspace_fs import PathAccessPolicy, classify_path, resolve_requested_path


_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_EXACT_PATH_FIELD_NAMES = {
    "path",
    "paths",
    "file",
    "files",
    "filepath",
    "filepaths",
    "file_path",
    "file_paths",
    "filename",
    "filenames",
    "file_name",
    "file_names",
    "dir",
    "dirs",
    "directory",
    "directories",
    "cwd",
    "root",
    "roots",
}
_PATH_FIELD_SUFFIXES = {
    "path",
    "paths",
    "file",
    "files",
    "filepath",
    "filepaths",
    "filename",
    "filenames",
    "dir",
    "dirs",
    "directory",
    "directories",
    "cwd",
    "root",
    "roots",
}


def validate_mcp_argument_paths(policy: PathAccessPolicy, arguments: dict) -> list[str]:
    reasons: list[str] = []
    seen: set[str] = set()
    for raw_value in _iter_mcp_path_values(arguments):
        candidate = _normalize_candidate_path(raw_value)
        if candidate is None:
            continue
        path = _resolve_candidate_path(policy, candidate)
        state = classify_path(policy, path)
        if state == "protected":
            reason = f"mcp_path_protected:{path}"
        else:
            try:
                path.relative_to(policy.workspace.resolve())
            except ValueError:
                reason = f"mcp_path_outside_workspace:{path}"
            else:
                continue
        if reason in seen:
            continue
        seen.add(reason)
        reasons.append(reason)
    return reasons


def _iter_mcp_path_values(value: object, current_key: str | None = None) -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        if current_key and _is_path_field_name(current_key):
            for nested in value.values():
                matches.extend(_iter_mcp_path_values(nested, current_key))
        for key, nested in value.items():
            if not isinstance(key, str):
                continue
            matches.extend(_iter_mcp_path_values(nested, key))
        return matches
    if isinstance(value, list):
        for nested in value:
            matches.extend(_iter_mcp_path_values(nested, current_key))
        return matches
    if isinstance(value, str) and current_key and _is_path_field_name(current_key):
        matches.append(value)
    return matches


def _is_path_field_name(raw_name: str) -> bool:
    normalized = _normalize_field_name(raw_name)
    if normalized in _EXACT_PATH_FIELD_NAMES:
        return True
    tokens = [token for token in normalized.split("_") if token]
    if not tokens:
        return False
    if tokens[-1] in _PATH_FIELD_SUFFIXES:
        return True
    return any(token in {"path", "paths", "cwd", "dir", "dirs", "directory", "directories", "root", "roots"} for token in tokens)


def _normalize_field_name(raw_name: str) -> str:
    with_boundaries = _CAMEL_BOUNDARY_RE.sub(r"\1_\2", raw_name)
    return re.sub(r"[^a-z0-9]+", "_", with_boundaries.lower()).strip("_")


def _normalize_candidate_path(raw_value: str) -> str | None:
    candidate = raw_value.strip()
    if not candidate or "\n" in candidate or "\r" in candidate:
        return None
    if candidate.startswith("file://"):
        parsed = urlparse(candidate)
        if parsed.scheme != "file":
            return None
        netloc = f"//{parsed.netloc}" if parsed.netloc and parsed.netloc != "localhost" else ""
        path = unquote(parsed.path or "")
        normalized = f"{netloc}{path}".strip()
        return normalized or None
    if "://" in candidate:
        return None
    return candidate


def _resolve_candidate_path(policy: PathAccessPolicy, candidate: str) -> Path:
    expanded = Path(candidate).expanduser()
    return resolve_requested_path(policy, str(expanded))
