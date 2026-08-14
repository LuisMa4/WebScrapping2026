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
    """
    Autentica via OAuth2 con una cuenta personal de Google -- NO cuenta de
    servicio. Verificado en vivo (2026-08-11): una cuenta de servicio puede
    crear carpetas (son solo metadatos) pero NO puede subir archivos a una
    carpeta de Drive personal -- falla con "Service Accounts do not have
    storage quota", porque no tienen cuota propia y esa funcion requiere
    Shared Drives (exclusivo de Google Workspace pagado). OAuth con la
    cuenta del usuario si tiene cuota real.

    `credentials_path` apunta al "OAuth client ID" (tipo Desktop app)
    descargado de Google Cloud Console -- NO al JSON de una cuenta de
    servicio. El token resultante (con refresh token) se guarda como
    `token.json` junto a ese archivo: la PRIMERA vez abre el navegador para
    que el usuario autorice una sola vez; en corridas siguientes reutiliza
    o renueva el token automaticamente sin pedir login de nuevo -- por eso
    esto sigue siendo apto para la Tarea Programada semanal desatendida
    despues de esa unica autorizacion inicial.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds_path = Path(credentials_path)
    token_path = creds_path.parent / "google_oauth_token.json"

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), _DRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), _DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

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
