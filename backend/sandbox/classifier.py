from __future__ import annotations

from backend.sandbox.models import RunnerFailureRule


def matches_runner_failure(returncode: int | None, stderr: str, rules: tuple[RunnerFailureRule, ...]) -> bool:
    """Apply provider-owned runner failure rules before denial classification."""

    first_line = next((line.strip().lower() for line in stderr.splitlines() if line.strip()), "")
    stderr_lower = stderr.lower()
    for rule in rules:
        if rule.exit_codes and returncode not in rule.exit_codes:
            continue
        if rule.stderr_prefixes and any(first_line.startswith(prefix.lower()) for prefix in rule.stderr_prefixes):
            return True
        if rule.stderr_substrings and any(token.lower() in stderr_lower for token in rule.stderr_substrings):
            return True
    return False


def matches_denial_signature(stderr: str, signatures: tuple[str, ...]) -> bool:
    """Return whether stderr matches a provider-owned sandbox-denial dialect.

    Generic words such as ``permission denied`` are intentionally not baked
    into this helper. Providers must opt in with the exact diagnostics their
    runner/kernel emits, and callers must never use the result to run the
    command unsandboxed automatically.
    """

    if not signatures:
        return False
    stderr_lower = stderr.lower()
    return any(signature.lower() in stderr_lower for signature in signatures if signature)
