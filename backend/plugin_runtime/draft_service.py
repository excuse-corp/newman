from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .draft_models import (
    PluginDraftRecord,
    PluginSpec,
)
from .plugin_builder import build_plugin_package, normalize_plugin_name
from .plugin_intent_builder import build_plugin_spec_from_intent
from .plugin_risk_policy import assess_plugin_risk
from .plugin_review import build_plugin_review
from .plugin_validator import validate_plugin_package, validate_plugin_spec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PluginDraftService:
    def __init__(self, plugin_service, drafts_dir: Path):
        self.plugin_service = plugin_service
        self.drafts_dir = drafts_dir
        self.records_path = drafts_dir / "drafts.json"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[PluginDraftRecord]:
        payload = self._read_records()
        return [PluginDraftRecord.model_validate(item) for item in payload]

    def get(self, draft_id: str) -> PluginDraftRecord:
        for record in self.list():
            if record.draft_id == draft_id:
                return record
        raise FileNotFoundError(f"Plugin draft not found: {draft_id}")

    def create(self, spec: PluginSpec, *, source_request: str | None = None) -> PluginDraftRecord:
        validation = validate_plugin_spec(spec)
        risk = assess_plugin_risk(spec)
        draft_id = f"pd_{uuid4().hex}"
        package_path: str | None = None
        status = "draft"
        error: str | None = None
        if validation.ok:
            try:
                package_parent = self.drafts_dir / draft_id
                package_parent.mkdir(parents=True, exist_ok=False)
                package_path = str(build_plugin_package(spec, package_parent))
                status = "generated"
            except Exception as exc:
                status = "install_failed"
                error = str(exc)
        else:
            status = "validation_failed"
        now = _now()
        record = PluginDraftRecord(
            draft_id=draft_id,
            status=status,
            created_at=now,
            updated_at=now,
            plugin_name=normalize_plugin_name(spec.name),
            spec=spec,
            source_request=source_request,
            package_path=package_path,
            package_files=_package_files(Path(package_path)) if package_path else [],
            manifest_content=_manifest_content(Path(package_path)) if package_path else None,
            validation=validation,
            risk=risk,
            review=build_plugin_review(
                self.plugin_service,
                spec,
                normalize_plugin_name(spec.name),
                Path(package_path) if package_path else None,
            ),
            error=error,
        )
        self._save(record)
        return record

    def create_from_request(self, request: str) -> PluginDraftRecord:
        return self.create(build_plugin_spec_from_intent(request), source_request=request.strip())

    def validate(self, draft_id: str) -> PluginDraftRecord:
        record = self.get(draft_id)
        if not record.package_path:
            raise ValueError("Plugin draft has no generated package")
        report = validate_plugin_package(Path(record.package_path), record.spec)
        record.package_files = _package_files(Path(record.package_path))
        record.manifest_content = _manifest_content(Path(record.package_path))
        record.validation = report
        record.review = self._build_review(record)
        record.updated_at = _now()
        record.status = "awaiting_approval" if report.ok else "validation_failed"
        record.error = None if report.ok else "; ".join(report.errors)
        self._save(record)
        return record

    def approve(self, draft_id: str, *, confirm: bool) -> PluginDraftRecord:
        record = self.get(draft_id)
        if not confirm:
            raise ValueError("安装插件必须明确确认")
        if record.status != "awaiting_approval":
            raise ValueError(f"当前草稿状态不能审批: {record.status}")
        record.status = "approved"
        record.updated_at = _now()
        self._save(record)
        return record

    def install(self, draft_id: str) -> PluginDraftRecord:
        record = self.get(draft_id)
        if record.status != "approved":
            raise ValueError(f"当前草稿状态不能安装: {record.status}")
        if not record.package_path:
            raise ValueError("Plugin draft has no generated package")
        package_path = Path(record.package_path).resolve()
        package_report = validate_plugin_package(package_path, record.spec)
        record.package_files = _package_files(package_path)
        record.manifest_content = _manifest_content(package_path)
        record.review = self._build_review(record)
        if not package_report.ok:
            record.validation = package_report
            record.status = "validation_failed"
            record.error = "; ".join(package_report.errors)
            record.updated_at = _now()
            self._save(record)
            raise ValueError(record.error)

        target = (self.plugin_service.plugins_dir / package_path.name).resolve()
        if target.exists() or any(item.name == record.plugin_name for item in self.plugin_service.list_plugins()):
            raise FileExistsError(f"Plugin 已存在：{record.plugin_name}")
        self.plugin_service.plugins_dir.mkdir(parents=True, exist_ok=True)
        temporary_target = Path(tempfile.mkdtemp(prefix=f".{package_path.name}-", dir=self.plugin_service.plugins_dir))
        shutil.rmtree(temporary_target)
        try:
            shutil.copytree(package_path, temporary_target)
            os.replace(temporary_target, target)
        except Exception as exc:
            if temporary_target.exists():
                shutil.rmtree(temporary_target, ignore_errors=True)
            record.status = "install_failed"
            record.error = str(exc)
            record.updated_at = _now()
            self._save(record)
            raise

        self.plugin_service.reload()
        record.status = "installed_disabled"
        record.installed_path = str(target)
        record.updated_at = _now()
        self._save(record)
        return record

    def review(self, draft_id: str) -> PluginDraftRecord:
        record = self.get(draft_id)
        record.package_files = _package_files(Path(record.package_path)) if record.package_path else []
        record.manifest_content = _manifest_content(Path(record.package_path)) if record.package_path else None
        record.review = self._build_review(record)
        record.updated_at = _now()
        self._save(record)
        return record

    def reject(self, draft_id: str) -> PluginDraftRecord:
        record = self.get(draft_id)
        if record.status in {"installed_disabled", "rolled_back"}:
            raise ValueError("已安装的插件不能拒绝，请使用回滚")
        record.status = "rejected"
        record.updated_at = _now()
        self._save(record)
        return record

    def rollback(self, draft_id: str) -> PluginDraftRecord:
        record = self.get(draft_id)
        if record.status not in {"installed_disabled", "approved"} or not record.installed_path:
            raise ValueError("当前草稿没有可回滚的已安装插件")
        plugin_path = Path(record.installed_path).resolve()
        if plugin_path.exists():
            shutil.rmtree(plugin_path)
        self.plugin_service.registry.delete(record.plugin_name)
        self.plugin_service.reload()
        record.status = "rolled_back"
        record.updated_at = _now()
        self._save(record)
        return record

    def _read_records(self) -> list[dict]:
        if not self.records_path.exists():
            return []
        payload = json.loads(self.records_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []

    def _save(self, record: PluginDraftRecord) -> None:
        records = [item for item in self._read_records() if item.get("draft_id") != record.draft_id]
        records.append(record.model_dump(mode="json"))
        temporary = self.records_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.records_path)

    def _build_review(self, record: PluginDraftRecord):
        return build_plugin_review(
            self.plugin_service,
            record.spec,
            record.plugin_name,
            Path(record.package_path) if record.package_path else None,
        )


def _package_files(package_path: Path) -> list[str]:
    if not package_path.exists():
        return []
    return sorted(
        path.relative_to(package_path).as_posix()
        for path in package_path.rglob("*")
        if path.is_file()
    )


def _manifest_content(package_path: Path) -> str | None:
    manifest_path = package_path / "plugin.yaml"
    return manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else None
