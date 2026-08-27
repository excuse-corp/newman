# Newman Windows ACL helper

This directory owns the native helper for `windows_acl`.

Current state: Windows implementation source is present, with a non-Windows
fail-closed stub for local builds. The Python `WindowsAclProvider` builds the
stable helper argv and requires this binary to pass a functional probe before any
command can run. A non-Windows build, a missing helper, or a helper-side failure
exits with the runner-failure contract:

```text
stderr prefix: newman-windows-acl-run:
exit code: 127
```

Implemented Windows helper behavior:

- Parses `newman-sandbox-win.exe run --workspace <dir> --temp <dir> --mode <read-only|workspace-write> [--write-sid <sid> --temp-write-sid <sid>] -- <argv...>`.
- Creates a `WRITE_RESTRICTED` token with mode-specific restricting SIDs.
- Materializes workspace/temp NTFS write ACEs; workspace grants stand, temp grants are best-effort revoked.
- Spawns the target with `CreateProcessAsUserW` and inherited stdio.
- Places the child in a kill-on-close Job Object.
- Mirrors the child exit code.
- Never spawns the target unrestricted on helper failure.

Windows validation still needs to run on Windows 10/11 CI or a Windows host:

```powershell
cmake -S backend/sandbox/windows_runner -B build/windows_runner
cmake --build build/windows_runner --config Release
$env:NEWMAN_SANDBOX_PROVIDER_PATH = "$PWD\build\windows_runner\Release\newman-sandbox-win.exe"
python -m pytest -q backend/tests/test_cross_platform_sandbox_e2e.py backend/tests/test_windows_acl_provider.py
```
