from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Mapping


DEFAULT_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "LANG",
    "LC_*",
    "TMPDIR",
    "TMP",
    "TEMP",
    "NEWMAN_RUNTIME_WORKSPACE",
    "NEWMAN_PLUGIN_ROOT",
    "NEWMAN_PLUGIN_NAME",
    "NEWMAN_LARK_DEFAULT_IM_USER_ID",
    "NEWMAN_LARK_DEFAULT_IM_IDENTITY",
)

SECRET_NAME_MARKERS = (
    "TOKEN",
    "SECRET",
    "API_KEY",
    "APIKEY",
    "PASSWORD",
    "PRIVATE_KEY",
    "CREDENTIAL",
    "ACCESS_KEY",
)


def sanitize_environment(
    overrides: Mapping[str, str] | None = None,
    *,
    allowlist: tuple[str, ...] | list[str] | None = None,
    workspace: Path | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Return a minimal child environment and the keys that were removed.

    Secret-looking names are denied even when a broad wildcard is configured.
    This keeps a plugin-provided ``env`` mapping from silently reintroducing
    the parent process credentials.
    """

    patterns = tuple(allowlist or DEFAULT_ENV_ALLOWLIST)
    source = dict(os.environ)
    explicit = {str(key): str(value) for key, value in (overrides or {}).items()}
    source.update(explicit)

    result: dict[str, str] = {}
    filtered: list[str] = []
    for key, value in source.items():
        explicitly_declared = key in explicit
        if _is_secret_name(key) or (
            not explicitly_declared and not any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)
        ):
            filtered.append(key)
            continue
        result[key] = value

    if workspace is not None:
        result["NEWMAN_RUNTIME_WORKSPACE"] = str(workspace.resolve())
    if "PATH" not in result:
        result["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    return result, sorted(set(filtered))


def _is_secret_name(name: str) -> bool:
    normalized = name.upper()
    return any(marker in normalized for marker in SECRET_NAME_MARKERS)
