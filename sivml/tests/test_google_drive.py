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
