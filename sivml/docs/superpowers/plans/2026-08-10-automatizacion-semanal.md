# Automatización Semanal (4 plantillas fijas + Google Drive) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Monday, automatically run the 4 fixed study templates (Derecho Administrativo, Derecho Constitucional, Derecho Civil, Ingeniería Civil) with a 7-day date range, upload their Excel results to a dated folder in a specific Google Drive folder, with a dashboard toggle to turn the whole cycle on/off — and clean up the database so only these 4 templates (and no historical studies) remain.

**Architecture:** A standalone script (`weekly_run.py`) triggered by a Windows Task Scheduler task calls the existing `study_runner.execute_study()` pipeline (scraping → dedup → Excel export) sequentially for each of 4 templates, then uploads the resulting Excel files to Google Drive via a service account. A new `AutomationSettings` DB row (singleton) holds the on/off flag and last-run status, editable from a new dashboard section that also offers a "Probar ahora" (run now) button and a "Install scheduled task" button.

**Tech Stack:** Python 3.14, SQLAlchemy 2.0, Streamlit, `google-api-python-client` + `google-auth` (new), Windows `schtasks` CLI (no new dependency).

## Global Constraints

- The 4 templates to automate are `StudyTemplate` ids **8, 9, 10, 11** in the current `sivml.db` (Ingeniería Civil, Derecho Civil, Derecho Constitucional, Derecho Administrativo respectively — verified against the real DB, see spec).
- Target Drive folder ID: `1-AkvMOuf7tQYWGbkKSxGRCqYxiEOfHk1` (from `https://drive.google.com/drive/folders/1-AkvMOuf7tQYWGbkKSxGRCqYxiEOfHk1`).
- Date range for each automated run: `date.today() - timedelta(days=7)` to `date.today()`.
- Weekly schedule default time: **07:00**, configurable via `--hora HH:MM` at install time.
- Service-account credentials file path: `sivml/credentials/google_service_account.json` (never committed — must be gitignored).
- All new DB-touching code must go through `database/repository.py` functions, never raw session queries elsewhere (existing project convention).
- All background/standalone execution (weekly_run.py) must not import Streamlit, matching `study_runner.py`'s existing "no Streamlit here" constraint.
- Every new module needs unit tests using the project's existing in-memory-SQLite + monkeypatch pattern (see `tests/test_study_runner.py`, `tests/test_templates.py`).
- Full spec: `docs/superpowers/specs/2026-08-10-automatizacion-semanal-design.md`.

---

## Task 1: `AutomationSettings` model + repository functions

**Files:**
- Modify: `database/models.py` (add class after `StudyTemplate`, around line 167)
- Modify: `database/repository.py` (add imports + new section at end of file)
- Test: `tests/test_automation_settings.py` (new)

**Interfaces:**
- Produces: `database.models.AutomationSettings` (columns: `id`, `enabled`, `drive_folder_id`, `template_ids_json`, `last_run_at`, `last_run_status`, `last_run_message`; property `template_ids: list[int]`).
- Produces: `repo.get_automation_settings(session) -> AutomationSettings`, `repo.set_automation_enabled(session, enabled: bool) -> AutomationSettings`, `repo.record_automation_run(session, status: str, message: str) -> AutomationSettings`.
- Produces constants: `repo.DEFAULT_AUTOMATION_TEMPLATE_IDS = [8, 9, 10, 11]`, `repo.DEFAULT_AUTOMATION_DRIVE_FOLDER_ID = "1-AkvMOuf7tQYWGbkKSxGRCqYxiEOfHk1"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_automation_settings.py`:

```python
"""Tests de la configuracion de la automatizacion semanal (AutomationSettings)."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.session import Base
from database import repository as repo


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


class TestGetAutomationSettings:
    def test_creates_default_row_when_missing(self, session):
        settings = repo.get_automation_settings(session)
        assert settings.id == 1
        assert settings.enabled is False
        assert settings.drive_folder_id == repo.DEFAULT_AUTOMATION_DRIVE_FOLDER_ID
        assert settings.template_ids == repo.DEFAULT_AUTOMATION_TEMPLATE_IDS

    def test_returns_same_row_on_second_call(self, session):
        first = repo.get_automation_settings(session)
        repo.set_automation_enabled(session, True)
        second = repo.get_automation_settings(session)
        assert second.id == first.id
        assert second.enabled is True


class TestSetAutomationEnabled:
    def test_toggles_on(self, session):
        settings = repo.set_automation_enabled(session, True)
        assert settings.enabled is True

    def test_toggles_off(self, session):
        repo.set_automation_enabled(session, True)
        settings = repo.set_automation_enabled(session, False)
        assert settings.enabled is False


class TestRecordAutomationRun:
    def test_updates_status_fields(self, session):
        settings = repo.record_automation_run(session, status="success", message="4/4 OK")
        assert settings.last_run_status == "success"
        assert settings.last_run_message == "4/4 OK"
        assert settings.last_run_at is not None

    def test_overwrites_previous_run(self, session):
        repo.record_automation_run(session, status="failed", message="boom")
        settings = repo.record_automation_run(session, status="success", message="ok now")
        assert settings.last_run_status == "success"
        assert settings.last_run_message == "ok now"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sivml && python -m pytest tests/test_automation_settings.py -v`
Expected: FAIL with `AttributeError: module 'database.repository' has no attribute 'get_automation_settings'` (or similar — the model/functions don't exist yet).

- [ ] **Step 3: Add the `AutomationSettings` model**

In `database/models.py`, add this class immediately after the `StudyTemplate` class (after its `portals` setter, before `class ScrapingRun`):

```python
class AutomationSettings(Base):
    """Configuracion de la automatizacion semanal (fila unica, id=1)."""
    __tablename__ = "automation_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    drive_folder_id: Mapped[str | None] = mapped_column(String(255))
    template_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_run_status: Mapped[str | None] = mapped_column(String(20))  # success|partial|failed
    last_run_message: Mapped[str | None] = mapped_column(Text)

    @property
    def template_ids(self) -> list[int]:
        return json.loads(self.template_ids_json)

    @template_ids.setter
    def template_ids(self, value: list[int]) -> None:
        self.template_ids_json = json.dumps(value)
```

This is a brand-new table, so `Base.metadata.create_all()` (already called by `init_db()`) will create it automatically — no lightweight-migration entry needed (those are only for adding columns to *existing* tables).

- [ ] **Step 4: Add the repository functions**

In `database/repository.py`, change the models import line (currently `from database.models import Job, RawJob, ScrapingRun, Study, StudyTemplate`) to:

```python
from database.models import AutomationSettings, Job, RawJob, ScrapingRun, Study, StudyTemplate
```

Then append this new section at the end of the file:

```python
# ---------------------------------------------------------------------------
# Automatizacion semanal
# ---------------------------------------------------------------------------

DEFAULT_AUTOMATION_TEMPLATE_IDS = [8, 9, 10, 11]
DEFAULT_AUTOMATION_DRIVE_FOLDER_ID = "1-AkvMOuf7tQYWGbkKSxGRCqYxiEOfHk1"


def get_automation_settings(session: Session) -> AutomationSettings:
    """
    Devuelve la fila unica (id=1) de configuracion de la automatizacion
    semanal, creandola con los defaults del proyecto (las 4 plantillas fijas
    y la carpeta de Drive ya conocida) si todavia no existe.
    """
    settings = session.get(AutomationSettings, 1)
    if settings is None:
        settings = AutomationSettings(
            id=1,
            enabled=False,
            drive_folder_id=DEFAULT_AUTOMATION_DRIVE_FOLDER_ID,
            template_ids_json=json.dumps(DEFAULT_AUTOMATION_TEMPLATE_IDS),
        )
        session.add(settings)
        session.commit()
    return settings


def set_automation_enabled(session: Session, enabled: bool) -> AutomationSettings:
    settings = get_automation_settings(session)
    settings.enabled = enabled
    session.commit()
    return settings


def record_automation_run(session: Session, status: str, message: str) -> AutomationSettings:
    settings = get_automation_settings(session)
    settings.last_run_at = datetime.utcnow()
    settings.last_run_status = status
    settings.last_run_message = message
    session.commit()
    return settings
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd sivml && python -m pytest tests/test_automation_settings.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Run the full suite to check nothing broke**

Run: `cd sivml && python -m pytest tests/ -q`
Expected: all tests pass (261 previously + 6 new = 267).

- [ ] **Step 7: Commit**

```bash
git add database/models.py database/repository.py tests/test_automation_settings.py
git commit -m "feat: add AutomationSettings model and repository functions for weekly automation"
```

---

## Task 2: Google Drive integration layer

**Files:**
- Create: `integrations/__init__.py` (empty)
- Create: `integrations/google_drive.py`
- Test: `tests/test_google_drive.py` (new)
- Modify: `requirements.txt`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `google_drive.get_drive_service(credentials_path: str)`, `google_drive.create_dated_folder(service, parent_folder_id: str, date_str: str) -> str`, `google_drive.upload_file(service, folder_id: str, file_path: Path) -> str`, `google_drive.upload_files_to_dated_folder(credentials_path: str, parent_folder_id: str, date_str: str, file_paths: list[Path]) -> UploadResult` where `UploadResult` is a `NamedTuple(folder_id: str, folder_url: str, uploaded: list[str], failed: list[tuple[Path, str]])`.

- [ ] **Step 1: Add new dependencies and install them**

Add to `requirements.txt` (after `psutil>=6.0`):

```
google-api-python-client>=2.130
google-auth>=2.30
```

Run: `cd sivml && pip install -r requirements.txt`
Expected: both packages install successfully.

- [ ] **Step 2: Add credentials/ to .gitignore**

Add this line to `.gitignore` (anywhere, e.g. after `.env`):

```
credentials/
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_google_drive.py`:

```python
"""
Tests de integrations/google_drive.py contra un servicio de Drive FALSO (sin
red, sin credenciales reales) -- imita la forma exacta en que
googleapiclient encadena files().list()/.create()/.execute(), para que el
codigo de produccion no tenga que cambiar para ser testeable.
"""
import re

import pytest

from integrations import google_drive


class _FakeExecutable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeFiles:
    def __init__(self):
        self.folders: dict[str, dict] = {}       # id -> {"name", "parent"}
        self.created_files: list[dict] = []       # [{"id", "name", "parents"}]
        self._next_id = 0

    def _new_id(self) -> str:
        self._next_id += 1
        return f"fake-id-{self._next_id}"

    def list(self, q, fields, spaces):
        parent = re.search(r"'([^']+)' in parents", q).group(1)
        name = re.search(r"name = '([^']+)'", q).group(1)
        matches = [
            {"id": fid, "name": meta["name"]}
            for fid, meta in self.folders.items()
            if meta["parent"] == parent and meta["name"] == name
        ]
        return _FakeExecutable({"files": matches})

    def create(self, body, fields, media_body=None):
        new_id = self._new_id()
        if media_body is not None:
            self.created_files.append({"id": new_id, "name": body["name"], "parents": body["parents"]})
        else:
            self.folders[new_id] = {"name": body["name"], "parent": body["parents"][0]}
        return _FakeExecutable({"id": new_id})


class FakeDriveService:
    def __init__(self):
        self._files = _FakeFiles()

    def files(self):
        return self._files


class TestCreateDatedFolder:
    def test_creates_new_folder(self):
        service = FakeDriveService()
        folder_id = google_drive.create_dated_folder(service, "parent-1", "2026-08-10")
        assert folder_id in service.files().folders
        assert service.files().folders[folder_id] == {"name": "2026-08-10", "parent": "parent-1"}

    def test_reuses_existing_folder_instead_of_duplicating(self):
        service = FakeDriveService()
        first = google_drive.create_dated_folder(service, "parent-1", "2026-08-10")
        second = google_drive.create_dated_folder(service, "parent-1", "2026-08-10")
        assert first == second
        assert len(service.files().folders) == 1

    def test_different_dates_create_different_folders(self):
        service = FakeDriveService()
        first = google_drive.create_dated_folder(service, "parent-1", "2026-08-10")
        second = google_drive.create_dated_folder(service, "parent-1", "2026-08-17")
        assert first != second
        assert len(service.files().folders) == 2


class TestUploadFile:
    def test_uploads_and_returns_file_id(self, tmp_path):
        service = FakeDriveService()
        folder_id = google_drive.create_dated_folder(service, "parent-1", "2026-08-10")
        file_path = tmp_path / "SIVML_test.xlsx"
        file_path.write_text("contenido de prueba")

        file_id = google_drive.upload_file(service, folder_id, file_path)

        assert any(f["id"] == file_id for f in service.files().created_files)
        uploaded = next(f for f in service.files().created_files if f["id"] == file_id)
        assert uploaded["name"] == "SIVML_test.xlsx"
        assert uploaded["parents"] == [folder_id]


class TestUploadFilesToDatedFolder:
    def test_uploads_all_files_to_a_new_dated_folder(self, monkeypatch, tmp_path):
        service = FakeDriveService()
        monkeypatch.setattr(google_drive, "get_drive_service", lambda path: service)

        f1 = tmp_path / "a.xlsx"; f1.write_text("x")
        f2 = tmp_path / "b.xlsx"; f2.write_text("x")

        result = google_drive.upload_files_to_dated_folder(
            credentials_path="fake.json",
            parent_folder_id="parent-1",
            date_str="2026-08-10",
            file_paths=[f1, f2],
        )

        assert len(result.uploaded) == 2
        assert result.failed == []
        assert result.folder_url == f"https://drive.google.com/drive/folders/{result.folder_id}"

    def test_isolates_a_failing_file_and_still_uploads_the_rest(self, monkeypatch, tmp_path):
        service = FakeDriveService()
        monkeypatch.setattr(google_drive, "get_drive_service", lambda path: service)

        def fake_upload_file(svc, folder_id, path):
            if path.name == "broken.xlsx":
                raise RuntimeError("disk error")
            return f"uploaded-{path.name}"

        monkeypatch.setattr(google_drive, "upload_file", fake_upload_file)

        good = tmp_path / "good.xlsx"; good.write_text("x")
        bad = tmp_path / "broken.xlsx"; bad.write_text("x")

        result = google_drive.upload_files_to_dated_folder(
            credentials_path="fake.json",
            parent_folder_id="parent-1",
            date_str="2026-08-10",
            file_paths=[good, bad],
        )

        assert result.uploaded == ["uploaded-good.xlsx"]
        assert len(result.failed) == 1
        assert result.failed[0][0] == bad
        assert "disk error" in result.failed[0][1]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd sivml && python -m pytest tests/test_google_drive.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'integrations'`.

- [ ] **Step 5: Implement `integrations/google_drive.py`**

Create `integrations/__init__.py` (empty file).

Create `integrations/google_drive.py`:

```python
"""
Capa delgada sobre la API de Google Drive (google-api-python-client), usada
por weekly_run.py para subir los Excel de la corrida semanal. Cada funcion
recibe `service` como parametro en vez de construirlo internamente (salvo
get_drive_service, la unica que toca red/autenticacion de verdad) -- asi los
tests le pasan un objeto falso sin necesitar credenciales reales ni red.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

_DRIVE_MIME_FOLDER = "application/vnd.google-apps.folder"
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service(credentials_path: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=_DRIVE_SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def create_dated_folder(service, parent_folder_id: str, date_str: str) -> str:
    """Reutiliza la carpeta si ya existe (por si el script corre dos veces el
    mismo dia -- ej. una corrida automatica y luego 'Probar ahora') en vez de
    crear duplicados."""
    query = (
        f"'{parent_folder_id}' in parents and name = '{date_str}' "
        f"and mimeType = '{_DRIVE_MIME_FOLDER}' and trashed = false"
    )
    result = service.files().list(q=query, fields="files(id, name)", spaces="drive").execute()
    existing = result.get("files", [])
    if existing:
        return existing[0]["id"]

    metadata = {"name": date_str, "mimeType": _DRIVE_MIME_FOLDER, "parents": [parent_folder_id]}
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_file(service, folder_id: str, file_path: Path) -> str:
    from googleapiclient.http import MediaFileUpload

    metadata = {"name": file_path.name, "parents": [folder_id]}
    media = MediaFileUpload(str(file_path), resumable=False)
    uploaded = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return uploaded["id"]


class UploadResult(NamedTuple):
    folder_id: str
    folder_url: str
    uploaded: list[str]
    failed: list[tuple[Path, str]]


def upload_files_to_dated_folder(
    credentials_path: str,
    parent_folder_id: str,
    date_str: str,
    file_paths: list[Path],
) -> UploadResult:
    """
    Sube cada archivo de file_paths a una subcarpeta `date_str` dentro de
    parent_folder_id. Un archivo que falle NO detiene la subida de los
    demas -- se reporta en `.failed` al final.
    """
    service = get_drive_service(credentials_path)
    folder_id = create_dated_folder(service, parent_folder_id, date_str)

    uploaded: list[str] = []
    failed: list[tuple[Path, str]] = []
    for path in file_paths:
        try:
            uploaded.append(upload_file(service, folder_id, path))
        except Exception as exc:
            failed.append((path, str(exc)))

    return UploadResult(
        folder_id=folder_id,
        folder_url=f"https://drive.google.com/drive/folders/{folder_id}",
        uploaded=uploaded,
        failed=failed,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd sivml && python -m pytest tests/test_google_drive.py -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Run the full suite**

Run: `cd sivml && python -m pytest tests/ -q`
Expected: all pass (267 previous + 6 new = 273).

- [ ] **Step 8: Commit**

```bash
git add integrations/ tests/test_google_drive.py requirements.txt .gitignore
git commit -m "feat: add Google Drive upload integration for weekly automation"
```

---

## Task 3: Make `study_runner.execute_study()` return the generated Excel path

**Files:**
- Modify: `study_runner.py:73-109` (the `execute_study` function)
- Test: `tests/test_study_runner.py` (add to existing `TestExecuteStudy` class)

**Interfaces:**
- Consumes: nothing new.
- Produces: `study_runner.execute_study(cfg, study_id, dry_run) -> Path | None` (previously returned `None` implicitly always — this is a backward-compatible change since no existing caller uses the return value).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_study_runner.py`, inside the existing `class TestExecuteStudy:` block (after `test_marks_completed_and_exports_excel_when_jobs_found`):

```python
    def test_returns_the_excel_path_when_one_is_generated(self, session, cfg, monkeypatch, tmp_path):
        monkeypatch.setattr(study_runner, "run_scraping", _fake_run_scraping_with_result)
        monkeypatch.setattr(study_runner, "OUTPUT_DIR", tmp_path)
        study = repo.create_study(session, cfg)
        study_id = study.id
        session.close()

        result = study_runner.execute_study(cfg, study_id, dry_run=False)

        assert result is not None
        assert result.exists()
        assert result.suffix == ".xlsx"

    def test_returns_none_when_no_jobs_found(self, session, cfg, monkeypatch, tmp_path):
        monkeypatch.setattr(study_runner, "run_scraping", _fake_run_scraping_no_results)
        monkeypatch.setattr(study_runner, "OUTPUT_DIR", tmp_path)
        study = repo.create_study(session, cfg)
        study_id = study.id
        session.close()

        result = study_runner.execute_study(cfg, study_id, dry_run=False)

        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sivml && python -m pytest tests/test_study_runner.py::TestExecuteStudy::test_returns_the_excel_path_when_one_is_generated -v`
Expected: FAIL with `assert None is not None` (function currently returns `None` always).

- [ ] **Step 3: Modify `execute_study` to return the path**

In `study_runner.py`, replace the `execute_study` function (currently lines 73-109):

```python
def execute_study(cfg: StudyConfig, study_id: str, dry_run: bool) -> Path | None:
    """
    Pipeline completo de un estudio: scraping -> finalizar -> deduplicar ->
    exportar a Excel. Cada estudio usa su PROPIA session (no se comparte
    entre hilos), igual que ya hace scraping.py para paralelizar portales
    dentro de un mismo estudio. Devuelve la ruta del Excel generado, o None
    si no se genero ninguno (sin ofertas, detenido, o fallo) -- usado por
    weekly_run.py para saber que archivos subir a Drive.
    """
    session = SessionLocal()
    excel_path: Path | None = None
    try:
        run_scraping(session, cfg, study_id, dry_run=dry_run)

        was_stopped = repo.is_stop_requested(session, study_id)

        # Deduplicar y exportar el Excel ANTES de marcar el estudio como
        # terminado (finish_study, mas abajo): el dashboard usa la
        # transicion de status "running" -> terminal para decidir cuando
        # mostrar el banner de descarga. Si finish_study se llamara primero,
        # un observador (el fragment de Mis Estudios, en otra pestana/hilo)
        # podia ver el estudio ya "completed" en una ventana en la que el
        # Excel todavia no existia -- reproducido en vivo: el banner
        # mostraba "sin ofertas para exportar" pese a que el estudio si
        # tenia resultados, porque el archivo aun se estaba generando.
        if not was_stopped:
            raw_total = len(repo.get_raw_jobs_for_study(session, study_id))
            if raw_total > 0:
                stats = run_exact_dedup(session, study_id)
                if stats["jobs_created"] > 0:
                    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                    excel_path = export_study_to_excel(session, study_id, output_dir=OUTPUT_DIR)

        repo.finish_study(session, study_id, success=True)
    except Exception:
        logger.error(f"Error ejecutando estudio {study_id}", exc_info=True)
        session.rollback()
        repo.finish_study(session, study_id, success=False)
    finally:
        session.close()
    return excel_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd sivml && python -m pytest tests/test_study_runner.py -v`
Expected: all `TestExecuteStudy` tests pass, including the 2 new ones.

- [ ] **Step 5: Run the full suite**

Run: `cd sivml && python -m pytest tests/ -q`
Expected: all pass (273 previous + 2 new = 275).

- [ ] **Step 6: Commit**

```bash
git add study_runner.py tests/test_study_runner.py
git commit -m "feat: make execute_study return the generated Excel path"
```

---

## Task 4: `weekly_run.py` orchestrator

**Files:**
- Create: `weekly_run.py` (root of `sivml/`)
- Test: `tests/test_weekly_run.py` (new)

**Interfaces:**
- Consumes: `repo.get_automation_settings`, `repo.get_template`, `repo.create_study`, `repo.mark_template_used`, `repo.record_automation_run` (Task 1); `study_runner.execute_study(cfg, study_id, dry_run) -> Path | None` (Task 3); `google_drive.upload_files_to_dated_folder(...) -> UploadResult` (Task 2).
- Produces: `weekly_run.run_weekly_automation() -> dict` (keys: `"ran": bool`, `"results": list[tuple[str, str|None, Path|None, str|None]]`, `"upload": UploadResult|None`, `"message": str`) and `weekly_run.main() -> int` (CLI entry point for Task Scheduler).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_weekly_run.py`:

```python
"""Tests del orquestador de la automatizacion semanal (weekly_run.py)."""
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import weekly_run
from database.session import Base
from database import repository as repo
from database.models import StudyTemplate
from integrations.google_drive import UploadResult


@pytest.fixture()
def engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture()
def TestSessionLocal(engine):
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def session(TestSessionLocal):
    s = TestSessionLocal()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def patch_session_local(monkeypatch, TestSessionLocal):
    monkeypatch.setattr(weekly_run, "SessionLocal", TestSessionLocal)


def _seed_template(session, tid: int, name: str) -> None:
    tpl = StudyTemplate(
        id=tid, name=name, academic_program="Test",
        keywords_json=json.dumps(["derecho"]), cities_json=json.dumps(["Lima"]),
        portals_json=json.dumps(["computrabajo"]), max_pages=5,
        delay_min=0.0, delay_max=0.0, headless=True, created_at=datetime.utcnow(),
    )
    session.add(tpl)
    session.commit()


def _seed_default_templates(session) -> None:
    for tid, name in [
        (8, "Ingenieria Civil"), (9, "Derecho Civil"),
        (10, "Derecho Constitucional"), (11, "Derecho Administrativo"),
    ]:
        _seed_template(session, tid, name)


class TestRunWeeklyAutomationDisabled:
    def test_does_nothing_when_disabled(self, session, monkeypatch):
        repo.set_automation_enabled(session, False)
        called = []
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: called.append(a))

        summary = weekly_run.run_weekly_automation()

        assert summary["ran"] is False
        assert called == []


class TestRunWeeklyAutomationEnabled:
    def test_runs_all_four_configured_templates_with_a_7_day_range(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")

        run_calls = []

        def fake_execute_study(cfg, study_id, dry_run):
            run_calls.append(cfg)
            return None

        monkeypatch.setattr(weekly_run.study_runner, "execute_study", fake_execute_study)

        summary = weekly_run.run_weekly_automation()

        assert summary["ran"] is True
        assert len(run_calls) == 4
        expected_from = date.today() - timedelta(days=7)
        expected_to = date.today()
        for cfg in run_calls:
            assert cfg.date_from == expected_from
            assert cfg.date_to == expected_to
            assert cfg.dry_run is False if hasattr(cfg, "dry_run") else True  # StudyConfig has no dry_run field

    def test_isolates_a_failing_template_and_still_runs_the_others(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")

        def flaky_execute_study(cfg, study_id, dry_run):
            if "Derecho Civil" in cfg.study_name:
                raise RuntimeError("portal caido")
            return None

        monkeypatch.setattr(weekly_run.study_runner, "execute_study", flaky_execute_study)

        summary = weekly_run.run_weekly_automation()

        assert len(summary["results"]) == 4
        errors = [r[3] for r in summary["results"] if r[3] is not None]
        assert len(errors) == 1
        assert "portal caido" in errors[0]

    def test_skips_a_template_id_that_no_longer_exists(self, session, monkeypatch, tmp_path):
        _seed_template(session, 8, "Ingenieria Civil")  # solo sembramos 1 de las 4
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: None)

        summary = weekly_run.run_weekly_automation()

        missing = [r for r in summary["results"] if r[3] == "plantilla eliminada"]
        assert len(missing) == 3

    def test_uploads_generated_excels_when_credentials_file_exists(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)

        creds_path = tmp_path / "creds.json"
        creds_path.write_text("{}")
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", creds_path)

        excel = tmp_path / "SIVML_fake.xlsx"
        excel.write_text("fake")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: excel)

        upload_calls = []

        def fake_upload(credentials_path, parent_folder_id, date_str, file_paths):
            upload_calls.append((credentials_path, parent_folder_id, date_str, file_paths))
            return UploadResult(folder_id="f1", folder_url="https://drive/f1", uploaded=["id1"] * len(file_paths), failed=[])

        monkeypatch.setattr(weekly_run.google_drive, "upload_files_to_dated_folder", fake_upload)

        summary = weekly_run.run_weekly_automation()

        assert len(upload_calls) == 1
        _, parent_id, date_str, paths = upload_calls[0]
        assert parent_id == repo.DEFAULT_AUTOMATION_DRIVE_FOLDER_ID
        assert date_str == date.today().isoformat()
        assert len(paths) == 4
        assert summary["upload"].uploaded == ["id1"] * 4

    def test_skips_upload_when_credentials_file_missing(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "does_not_exist.json")

        excel = tmp_path / "SIVML_fake.xlsx"
        excel.write_text("fake")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: excel)

        called = []
        monkeypatch.setattr(
            weekly_run.google_drive, "upload_files_to_dated_folder",
            lambda **kw: called.append(kw),
        )

        summary = weekly_run.run_weekly_automation()

        assert called == []
        assert summary["upload"] is None
        assert "credenciales" in summary["message"].lower()

    def test_records_the_run_result_in_automation_settings(self, session, monkeypatch, tmp_path):
        _seed_default_templates(session)
        repo.set_automation_enabled(session, True)
        monkeypatch.setattr(weekly_run, "CREDENTIALS_PATH", tmp_path / "missing.json")
        monkeypatch.setattr(weekly_run.study_runner, "execute_study", lambda *a, **k: None)

        weekly_run.run_weekly_automation()

        settings = repo.get_automation_settings(session)
        assert settings.last_run_at is not None
        assert settings.last_run_status in ("success", "partial", "failed")
        assert "4/4" in settings.last_run_message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sivml && python -m pytest tests/test_weekly_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'weekly_run'`.

- [ ] **Step 3: Implement `weekly_run.py`**

Create `weekly_run.py` in the `sivml/` root (same level as `scraping.py`, `study_runner.py`):

```python
"""
Corrida semanal automatica de las 4 plantillas fijas + subida a Google
Drive. Disparado por la Tarea Programada de Windows los lunes (ver
scripts/install_weekly_task.py) -- tambien invocable a mano desde el boton
"Probar ahora" del dashboard (dashboard/app.py::page_mis_plantillas), o
desde linea de comandos: `python weekly_run.py`.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent

# La Tarea Programada de Windows arranca python.exe con cwd=%SystemRoot%\System32
# salvo que se configure lo contrario -- sqlite:///sivml.db (database/session.py)
# es una ruta RELATIVA que necesita cwd=sivml/. Debe ejecutarse ANTES de
# importar nada que toque database.session (crea el engine al importarse).
# Es un no-op cuando ya se corre desde sivml/ (dashboard, pytest, CLI).
if Path.cwd() != ROOT:
    os.chdir(ROOT)

from config.settings import ScraperConfig, StudyConfig
from database import repository as repo
from database.session import SessionLocal
from integrations import google_drive
import study_runner

logger = logging.getLogger("sivml.weekly_run")
CREDENTIALS_PATH = ROOT / "credentials" / "google_service_account.json"


def _build_cfg_from_template(tpl, date_from: date, date_to: date) -> StudyConfig:
    return StudyConfig(
        study_name=f"{tpl.name} ({date_from} / {date_to})",
        academic_program=tpl.academic_program,
        keywords=tpl.keywords,
        cities=tpl.cities,
        portals=tpl.portals,
        date_from=date_from,
        date_to=date_to,
        scraper=ScraperConfig(
            delay_range=(tpl.delay_min, tpl.delay_max),
            max_pages=tpl.max_pages,
            headless=tpl.headless,
        ),
    )


def run_weekly_automation() -> dict:
    """
    Ejecuta las plantillas configuradas en AutomationSettings (secuencial,
    una por una) y sube los Excel resultantes a Drive. Devuelve un resumen
    usado tanto por main() (log) como por el boton "Probar ahora" del
    dashboard (muestra el resultado al usuario):

        {
            "ran": bool,   # False si la automatizacion esta desactivada
            "results": [(template_name, study_id|None, excel_path|None, error|None), ...],
            "upload": UploadResult | None,
            "message": str,
        }
    """
    session = SessionLocal()
    try:
        settings = repo.get_automation_settings(session)
        if not settings.enabled:
            logger.info("Automatizacion desactivada, no se hace nada.")
            return {"ran": False, "results": [], "upload": None, "message": "Automatizacion desactivada."}

        today = date.today()
        date_from, date_to = today - timedelta(days=7), today
        template_ids = json.loads(settings.template_ids_json)

        results: list[tuple[str, str | None, Path | None, str | None]] = []
        for tid in template_ids:
            tpl = repo.get_template(session, tid)
            if tpl is None:
                results.append((f"[plantilla id {tid} no encontrada]", None, None, "plantilla eliminada"))
                continue
            try:
                cfg = _build_cfg_from_template(tpl, date_from, date_to)
                study = repo.create_study(session, cfg, status="running", dry_run=False)
                repo.mark_template_used(session, tpl.id)
                excel_path = study_runner.execute_study(cfg, study.id, dry_run=False)
                results.append((tpl.name, study.id, excel_path, None))
            except Exception as exc:
                logger.exception(f"Error corriendo plantilla {tpl.name}")
                results.append((tpl.name, None, None, str(exc)))

        excel_paths = [r[2] for r in results if r[2] is not None]
        upload_result = None
        if not excel_paths:
            upload_note = "Sin Excel generados, no se subio nada a Drive."
        elif not settings.drive_folder_id:
            upload_note = "Sin carpeta de Drive configurada, no se subio nada."
        elif not CREDENTIALS_PATH.exists():
            upload_note = (
                f"Archivo de credenciales no encontrado en {CREDENTIALS_PATH} "
                "-- sigue el instructivo para crear la cuenta de servicio."
            )
        else:
            try:
                upload_result = google_drive.upload_files_to_dated_folder(
                    credentials_path=str(CREDENTIALS_PATH),
                    parent_folder_id=settings.drive_folder_id,
                    date_str=today.isoformat(),
                    file_paths=excel_paths,
                )
                upload_note = f"Subidos {len(upload_result.uploaded)}/{len(excel_paths)} archivos a Drive."
                if upload_result.failed:
                    upload_note += f" {len(upload_result.failed)} fallaron."
            except Exception as exc:
                logger.exception("Error subiendo a Drive")
                upload_note = f"Error subiendo a Drive: {exc}"

        n_ok = sum(1 for r in results if r[3] is None)
        upload_ok = (not excel_paths) or (upload_result is not None and not upload_result.failed)
        if n_ok == 0:
            status = "failed"
        elif n_ok == len(results) and upload_ok:
            status = "success"
        else:
            status = "partial"

        message = f"{n_ok}/{len(results)} plantillas OK. {upload_note}"
        repo.record_automation_run(session, status=status, message=message)

        return {"ran": True, "results": results, "upload": upload_result, "message": message}
    finally:
        session.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    summary = run_weekly_automation()
    logger.info(summary["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd sivml && python -m pytest tests/test_weekly_run.py -v`
Expected: PASS (7 tests). Note: the `test_runs_all_four_configured_templates_with_a_7_day_range` test has an odd leftover assertion line (`cfg.dry_run is False if hasattr(...)`) — simplify it to just:
```python
        for cfg in run_calls:
            assert cfg.date_from == expected_from
            assert cfg.date_to == expected_to
```
(the earlier version was checking a field `StudyConfig` doesn't have — `dry_run` is a parameter to `execute_study`, not a `StudyConfig` field. Fix this in the test file before running.)

- [ ] **Step 5: Run the full suite**

Run: `cd sivml && python -m pytest tests/ -q`
Expected: all pass (275 previous + 7 new = 282).

- [ ] **Step 6: Commit**

```bash
git add weekly_run.py tests/test_weekly_run.py
git commit -m "feat: add weekly_run.py orchestrator for the 4-template automation"
```

---

## Task 5: Dashboard "Automatización semanal" section

**Files:**
- Modify: `dashboard/app.py` (add a new helper function + call it from `page_mis_plantillas()`)

**Interfaces:**
- Consumes: `repo.get_automation_settings`, `repo.set_automation_enabled` (Task 1); `weekly_run.run_weekly_automation` (Task 4).
- Produces: nothing consumed by later tasks (UI leaf).

- [ ] **Step 1: Add the `_render_automation_section` helper**

In `dashboard/app.py`, add this new function right before `def page_mis_plantillas():` (currently around line 802):

```python
def _render_automation_section(session) -> None:
    """
    Interruptor + estado + acciones de la automatizacion semanal (4
    plantillas fijas -> scraping -> Excel -> Drive, disparada por una Tarea
    Programada de Windows los lunes). Vive al principio de "Mis Plantillas".
    """
    from database import repository as repo

    settings = repo.get_automation_settings(session)

    with st.container(border=True):
        st.subheader("Automatizacion semanal")
        st.caption(
            "Corre las 4 plantillas fijas cada lunes con los ultimos 7 dias "
            "y sube los Excel a Google Drive."
        )

        new_enabled = st.toggle("Activa", value=settings.enabled, key="automation_enabled_toggle")
        if new_enabled != settings.enabled:
            repo.set_automation_enabled(session, new_enabled)
            st.rerun()

        if settings.last_run_at:
            last_run_str = settings.last_run_at.strftime("%Y-%m-%d %H:%M")
            st.caption(
                f"Ultima corrida: {last_run_str} -- **{settings.last_run_status}** -- "
                f"{settings.last_run_message}"
            )
        else:
            st.caption("Todavia no se ha corrido ninguna vez.")

        bcol1, bcol2 = st.columns(2)
        with bcol1:
            if st.button("Probar ahora", key="run_automation_now", use_container_width=True):
                import threading
                from weekly_run import run_weekly_automation

                threading.Thread(target=run_weekly_automation, daemon=True).start()
                st.info(
                    "Corrida iniciada en segundo plano -- sigue el progreso de "
                    "las 4 plantillas en **Mis Estudios**."
                )

        with bcol2:
            with st.popover("Instalar tarea programada de Windows"):
                st.caption(
                    "Crea una Tarea Programada de Windows que corre "
                    "`weekly_run.py` cada lunes a las 7:00 AM."
                )
                from scripts.install_weekly_task import build_schtasks_command
                st.code(" ".join(build_schtasks_command()))
                confirm_task = st.checkbox(
                    "Confirmo que quiero instalar esta tarea programada",
                    key="confirm_install_task",
                )
                if st.button("Instalar", key="install_task_btn"):
                    if confirm_task:
                        from scripts.install_weekly_task import install_task
                        ok, output = install_task()
                        if ok:
                            st.success("Tarea programada instalada correctamente.")
                        else:
                            st.error(f"No se pudo instalar: {output}")
                    else:
                        st.error("Marca la casilla de confirmacion primero.")
```

- [ ] **Step 2: Call it from `page_mis_plantillas()`**

In `dashboard/app.py`, inside `def page_mis_plantillas():`, right after `session = _session()` and its `try:` (currently around line 810-812, right before `templates = repo.list_templates(session)`), add the call:

```python
    session = _session()
    try:
        _render_automation_section(session)

        templates = repo.list_templates(session)
```

(Note: this creates a forward reference to `scripts.install_weekly_task`, built in Task 6 — that's fine, Python resolves the import lazily at button-click time, not at module load time, so `dashboard/app.py` will import cleanly even before Task 6 exists on disk, as long as Task 6 is completed before this button is actually clicked.)

- [ ] **Step 3: Verify the dashboard still starts and the new section renders**

This step needs Task 6 (`scripts/install_weekly_task.py`) to exist for the popover's `st.code()` line to not error when the "Mis Plantillas" page is opened (the `from scripts.install_weekly_task import build_schtasks_command` import happens inside the `with st.popover(...)` block, which only executes when a user actually opens/expands the popover — so the page itself loads fine either way, but do this verification AFTER Task 6 is done for a true end-to-end check). Run:

```bash
cd sivml
python -m streamlit run dashboard/app.py --server.headless true --server.port 8501
```

Then in a separate terminal, verify with a quick Playwright script:

```python
import sys, time
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 1200})
    page.goto("http://localhost:8501", timeout=30000)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    page.get_by_text("Mis Plantillas", exact=False).first.click()
    time.sleep(2)
    assert page.get_by_text("Automatizacion semanal", exact=False).count() > 0, "seccion no aparecio"
    assert page.get_by_text("Probar ahora", exact=False).count() > 0, "boton Probar ahora no aparecio"
    print("OK: seccion de automatizacion visible")
    browser.close()
```

Expected output: `OK: seccion de automatizacion visible`, no exceptions. Stop the Streamlit process afterward.

- [ ] **Step 4: Commit**

```bash
git add dashboard/app.py
git commit -m "feat: add weekly automation toggle and controls to Mis Plantillas"
```

---

## Task 6: `schtasks` installer script

**Files:**
- Create: `scripts/__init__.py` (empty)
- Create: `scripts/install_weekly_task.py`
- Test: `tests/test_install_weekly_task.py` (new — tests command construction only, not real `schtasks` execution)

**Interfaces:**
- Produces: `install_weekly_task.build_schtasks_command(hour_minute: str = "07:00", python_exe: str | None = None) -> list[str]`, `install_weekly_task.install_task(hour_minute: str = "07:00", python_exe: str | None = None) -> tuple[bool, str]`, `install_weekly_task.uninstall_task() -> tuple[bool, str]`, `install_weekly_task.TASK_NAME = "SIVML_CorridaSemanal"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_install_weekly_task.py`:

```python
"""Tests de construccion del comando schtasks (sin ejecutarlo de verdad)."""
from scripts import install_weekly_task


class TestBuildSchtasksCommand:
    def test_includes_task_name(self):
        cmd = install_weekly_task.build_schtasks_command()
        assert install_weekly_task.TASK_NAME in cmd

    def test_defaults_to_7am(self):
        cmd = install_weekly_task.build_schtasks_command()
        assert "07:00" in cmd

    def test_custom_hour_is_used(self):
        cmd = install_weekly_task.build_schtasks_command(hour_minute="09:30")
        assert "09:30" in cmd
        assert "07:00" not in cmd

    def test_schedules_weekly_on_monday(self):
        cmd = install_weekly_task.build_schtasks_command()
        assert "weekly" in cmd
        assert "MON" in cmd

    def test_uses_given_python_exe_and_script_path(self):
        cmd = install_weekly_task.build_schtasks_command(python_exe="C:\\fake\\python.exe")
        tr_index = cmd.index("/tr")
        tr_value = cmd[tr_index + 1]
        assert "C:\\fake\\python.exe" in tr_value
        assert "weekly_run.py" in tr_value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sivml && python -m pytest tests/test_install_weekly_task.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts'`.

- [ ] **Step 3: Implement `scripts/install_weekly_task.py`**

Create `scripts/__init__.py` (empty file).

Create `scripts/install_weekly_task.py`:

```python
"""
Registra (o quita) en el Programador de tareas de Windows la tarea que
corre weekly_run.py cada lunes. Uso standalone:
    python scripts/install_weekly_task.py [--hora HH:MM]
Tambien invocado desde el boton "Instalar tarea programada de Windows" del
dashboard (dashboard/app.py::_render_automation_section).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TASK_NAME = "SIVML_CorridaSemanal"
ROOT = Path(__file__).parent.parent


def build_schtasks_command(hour_minute: str = "07:00", python_exe: str | None = None) -> list[str]:
    python_exe = python_exe or sys.executable
    script_path = ROOT / "weekly_run.py"
    return [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'"{python_exe}" "{script_path}"',
        "/sc", "weekly",
        "/d", "MON",
        "/st", hour_minute,
        "/f",  # sobreescribe si ya existe -- permite re-instalar tras cambiar la hora
    ]


def install_task(hour_minute: str = "07:00", python_exe: str | None = None) -> tuple[bool, str]:
    cmd = build_schtasks_command(hour_minute, python_exe)
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    ok = result.returncode == 0
    output = result.stdout if ok else (result.stderr or result.stdout)
    return ok, output.strip()


def uninstall_task() -> tuple[bool, str]:
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True, text=True,
    )
    ok = result.returncode == 0
    output = result.stdout if ok else (result.stderr or result.stdout)
    return ok, output.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Instala la tarea programada semanal de SIVML.")
    parser.add_argument("--hora", default="07:00", help="Hora de ejecucion (HH:MM), default 07:00")
    args = parser.parse_args()
    ok, output = install_task(args.hora)
    print(output)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd sivml && python -m pytest tests/test_install_weekly_task.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Live-verify against the real Windows Task Scheduler (create + delete a throwaway task)**

**This step touches real Windows system state (Task Scheduler) — narrate exactly what's about to run before running it, since this is the kind of system-level action that needs to be transparent even though the user already approved the overall approach.**

Run this to confirm `schtasks /create` actually accepts the command as built (quoting is the main risk here):

```bash
cd sivml
python -c "
from scripts.install_weekly_task import install_task, uninstall_task
ok, output = install_task(hour_minute='07:00')
print('install ok:', ok)
print(output)
"
```

Expected: `install ok: True`.

Then verify it's really registered:

```bash
schtasks /query /tn SIVML_CorridaSemanal /v /fo list
```

Expected: shows the task with `Task To Run` pointing at the right `python.exe ... weekly_run.py` path, `Schedule Type: Weekly`, `Days: MON`, `Start Time: 7:00:00 AM`.

Then immediately clean it up (this test run was only to prove the installer works — the real install happens later, deliberately, when the user is ready to go live):

```bash
python -c "
from scripts.install_weekly_task import uninstall_task
ok, output = uninstall_task()
print('uninstall ok:', ok)
print(output)
"
```

Expected: `uninstall ok: True`. Confirm with `schtasks /query /tn SIVML_CorridaSemanal` that it now errors "cannot find the file specified" (task no longer exists).

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/install_weekly_task.py tests/test_install_weekly_task.py
git commit -m "feat: add Windows Task Scheduler installer for weekly automation"
```

---

## Task 7: One-time database cleanup script

**Files:**
- Create: `scripts/cleanup_for_automation.py`
- Test: `tests/test_cleanup_for_automation.py` (new)

**Interfaces:**
- Produces: `cleanup_for_automation.summarize(session) -> dict` (keys `templates_to_keep`, `templates_to_delete`, `studies_to_delete`), `cleanup_for_automation.run_cleanup(session, summary: dict) -> None`, `cleanup_for_automation.backup_db(root: Path) -> Path`, `cleanup_for_automation.KEEP_TEMPLATE_IDS = [8, 9, 10, 11]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cleanup_for_automation.py`:

```python
"""
Tests del script de limpieza unica (scripts/cleanup_for_automation.py)
contra una BD de PRUEBA sintetica -- nunca toca sivml.db real. Imita el
patron real encontrado en la BD del usuario: duplicados con/sin "Puno" y
plantillas de prueba viejas.
"""
import json
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.session import Base
from database import repository as repo
from database.models import Study, StudyTemplate
from config.settings import StudyConfig, ScraperConfig
from scripts import cleanup_for_automation


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _make_template(session, tid: int, name: str) -> None:
    tpl = StudyTemplate(
        id=tid, name=name, academic_program="Test",
        keywords_json=json.dumps(["x"]), cities_json=json.dumps(["Lima"]),
        portals_json=json.dumps(["computrabajo"]), created_at=datetime.utcnow(),
    )
    session.add(tpl)
    session.commit()


def _make_study(session, study_id: str, name: str) -> None:
    from datetime import date
    cfg = StudyConfig(
        study_id=study_id, study_name=name, academic_program="Test",
        keywords=["x"], cities=["Lima"], portals=["computrabajo"],
        date_from=date(2026, 1, 1), date_to=date(2026, 1, 7),
        scraper=ScraperConfig(),
    )
    repo.create_study(session, cfg, status="completed")


class TestSummarize:
    def test_identifies_templates_to_keep_and_delete(self, session):
        _make_template(session, 4, "Derecho Civil (viejo, con Puno)")
        _make_template(session, 9, "Derecho Civil")
        _make_template(session, 8, "Ingenieria Civil")
        _make_template(session, 10, "Derecho Constitucional")
        _make_template(session, 11, "Derecho Administrativo")
        _make_template(session, 1, "Prueba 1")

        summary = cleanup_for_automation.summarize(session)

        kept_ids = sorted(t.id for t in summary["templates_to_keep"])
        deleted_ids = sorted(t.id for t in summary["templates_to_delete"])
        assert kept_ids == [8, 9, 10, 11]
        assert deleted_ids == [1, 4]

    def test_all_studies_are_marked_for_deletion(self, session):
        _make_template(session, 8, "Ingenieria Civil")
        _make_study(session, "study-1", "Corrida vieja 1")
        _make_study(session, "study-2", "Corrida vieja 2")

        summary = cleanup_for_automation.summarize(session)

        study_ids = sorted(s.id for s in summary["studies_to_delete"])
        assert study_ids == ["study-1", "study-2"]


class TestRunCleanup:
    def test_deletes_everything_not_in_keep_list(self, session):
        _make_template(session, 4, "Derecho Civil (viejo)")
        _make_template(session, 9, "Derecho Civil")
        _make_study(session, "study-1", "Corrida vieja")

        summary = cleanup_for_automation.summarize(session)
        cleanup_for_automation.run_cleanup(session, summary)

        remaining_templates = session.scalars(select(StudyTemplate)).all()
        remaining_studies = session.scalars(select(Study)).all()
        assert [t.id for t in remaining_templates] == [9]
        assert remaining_studies == []


class TestBackupDb:
    def test_creates_a_dated_backup_copy(self, tmp_path):
        db_path = tmp_path / "sivml.db"
        db_path.write_bytes(b"fake sqlite content")

        backup_path = cleanup_for_automation.backup_db(tmp_path)

        assert backup_path.exists()
        assert backup_path.read_bytes() == b"fake sqlite content"
        assert "bak_pre_weekly_automation" in backup_path.name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sivml && python -m pytest tests/test_cleanup_for_automation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.cleanup_for_automation'`.

- [ ] **Step 3: Implement `scripts/cleanup_for_automation.py`**

```python
"""
Limpieza unica de la base de datos antes de activar la automatizacion
semanal: deja solo las 4 plantillas ya validadas (Derecho Administrativo,
Derecho Constitucional, Derecho Civil, Ingenieria Civil -- ids 8, 9, 10, 11
en la BD real) y borra todo lo demas (plantillas viejas/duplicadas + TODOS
los Estudios historicos). Hace un backup de sivml.db antes de tocar nada.

Se corre a mano UNA SOLA VEZ: `python scripts/cleanup_for_automation.py`
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Study, StudyTemplate

KEEP_TEMPLATE_IDS = [8, 9, 10, 11]


def backup_db(root: Path) -> Path:
    db_path = root / "sivml.db"
    backup_path = root / f"sivml.db.bak_pre_weekly_automation_{date.today().isoformat()}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def summarize(session: Session) -> dict:
    all_templates = session.scalars(select(StudyTemplate)).all()
    all_studies = session.scalars(select(Study)).all()
    return {
        "templates_to_keep": [t for t in all_templates if t.id in KEEP_TEMPLATE_IDS],
        "templates_to_delete": [t for t in all_templates if t.id not in KEEP_TEMPLATE_IDS],
        "studies_to_delete": all_studies,
    }


def run_cleanup(session: Session, summary: dict) -> None:
    from database import repository as repo

    for study in summary["studies_to_delete"]:
        repo.delete_study(session, study.id)
    for tpl in summary["templates_to_delete"]:
        repo.delete_template(session, tpl.id)


def main() -> int:
    from database.session import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        summary = summarize(session)

        print(f"Plantillas a CONSERVAR ({len(summary['templates_to_keep'])}):")
        for t in summary["templates_to_keep"]:
            print(f"  - [{t.id}] {t.name}")

        print(f"\nPlantillas a BORRAR ({len(summary['templates_to_delete'])}):")
        for t in summary["templates_to_delete"]:
            print(f"  - [{t.id}] {t.name}")

        print(f"\nEstudios a BORRAR ({len(summary['studies_to_delete'])}): TODOS los historicos.")

        if not summary["templates_to_keep"]:
            print(
                f"\n[ERROR] Ninguna de las 4 plantillas esperadas (ids {KEEP_TEMPLATE_IDS}) "
                "existe en la base de datos -- abortando sin tocar nada, revisa los ids "
                "antes de reintentar."
            )
            return 1

        answer = input("\nEscribe BORRAR para confirmar (cualquier otra cosa cancela): ")
        if answer.strip() != "BORRAR":
            print("Cancelado, no se borro nada.")
            return 0

        backup_path = backup_db(ROOT)
        print(f"\nBackup creado en: {backup_path}")

        run_cleanup(session, summary)
        print("Listo. Solo quedan las 4 plantillas indicadas, sin estudios historicos.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd sivml && python -m pytest tests/test_cleanup_for_automation.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite**

Run: `cd sivml && python -m pytest tests/ -q`
Expected: all pass (282 previous + 5 new [Task 6] + 4 new [Task 7] = 291).

- [ ] **Step 6: Commit the script itself (NOT the actual cleanup run yet)**

```bash
git add scripts/cleanup_for_automation.py tests/test_cleanup_for_automation.py
git commit -m "feat: add one-time DB cleanup script for weekly automation"
```

- [ ] **Step 7: Run the cleanup against the REAL `sivml.db` — irreversible, requires explicit go-ahead**

**Stop and confirm with the user before this step**, even though they already approved this scope during brainstorming — this is the actual destructive action, not a rehearsal. Show them the exact `summarize()` output (which templates/studies will be deleted) before typing `BORRAR`. Once confirmed:

```bash
cd sivml
python scripts/cleanup_for_automation.py
```

Type `BORRAR` at the prompt only after the user has seen and approved the printed summary. Expected: backup file `sivml.db.bak_pre_weekly_automation_<today>` created, script reports success. Verify afterward:

```bash
python -c "
from database.session import SessionLocal
from database import repository as repo
s = SessionLocal()
print('templates:', [(t.id, t.name) for t in repo.list_templates(s)])
print('studies:', len(repo.list_studies(s)))
s.close()
"
```

Expected: exactly 4 templates (ids 8, 9, 10, 11), 0 studies.

---

## Task 8: End-to-end live verification (blocked on user completing Google Cloud setup)

**Files:** none (verification only).

- [ ] **Step 1: Confirm the credentials file is in place**

Ask the user to confirm `sivml/credentials/google_service_account.json` exists (they place it there per the instructions already given). Verify:

```bash
cd sivml
python -c "from pathlib import Path; print(Path('credentials/google_service_account.json').exists())"
```

Expected: `True`.

- [ ] **Step 2: Run a real "Probar ahora" through the dashboard**

Launch the dashboard, open "Mis Plantillas", turn the toggle on, click "Probar ahora". Watch "Mis Estudios" for the 4 studies to complete (this takes real time — LinkedIn alone can take several minutes per keyword/city per the project's known timing, see architecture gotcha #12).

- [ ] **Step 3: Verify the Drive folder**

Once all 4 studies show `completed` in "Mis Estudios", check the shared Drive folder (`https://drive.google.com/drive/folders/1-AkvMOuf7tQYWGbkKSxGRCqYxiEOfHk1`) for a new subfolder named with today's date, containing 4 `.xlsx` files.

- [ ] **Step 4: Check the dashboard reflects success**

Reload "Mis Plantillas" — the "Ultima corrida" caption should show `success` (or `partial` with a clear reason if something didn't fully complete) and a message like "4/4 plantillas OK. Subidos 4/4 archivos a Drive."

- [ ] **Step 5: Only after this passes, install the real scheduled task**

```bash
cd sivml
python scripts/install_weekly_task.py --hora 07:00
```

Or use the "Instalar tarea programada de Windows" button in the dashboard. Confirm with `schtasks /query /tn SIVML_CorridaSemanal /v /fo list`.

---

## Self-Review Notes

- **Spec coverage:** AutomationSettings + toggle (Task 1, 5), Google Drive upload (Task 2), 4-template weekly orchestration with 7-day range (Task 4), Task Scheduler trigger (Task 6), DB cleanup with backup (Task 7), "Probar ahora" (Task 5), end-to-end validation (Task 8) — all spec sections are covered.
- **Fixed during self-review:** Task 4's test file originally had a broken assertion referencing a nonexistent `cfg.dry_run` field — corrected inline in Step 4's note (real fix applied: removed the invalid line, kept only `date_from`/`date_to` assertions, which are the fields that actually matter for this test).
- **Type consistency:** `execute_study(cfg, study_id, dry_run) -> Path | None` (Task 3) matches its usage in `weekly_run.py` (Task 4). `UploadResult` NamedTuple fields (`folder_id`, `folder_url`, `uploaded`, `failed`) are used consistently in Task 2's implementation, Task 2's tests, and Task 4's tests/implementation. `repo.DEFAULT_AUTOMATION_TEMPLATE_IDS`/`DEFAULT_AUTOMATION_DRIVE_FOLDER_ID` (Task 1) are referenced by name (not re-hardcoded) in Task 4's and Task 7's tests.
- Tasks 1-4 and 6-7 are fully automatable (TDD, no external dependencies). Task 5's Step 3 and Task 8 require a running dashboard / real Google credentials and are explicitly marked as live-verification steps, not unit tests — consistent with this project's established pattern of validating Streamlit UI behavior with real browser sessions rather than pytest (see `feedback_validation_methodology` project memory).
