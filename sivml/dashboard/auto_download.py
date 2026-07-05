from __future__ import annotations

import base64


def build_auto_download_html(file_bytes: bytes, filename: str, mime: str) -> str:
    """HTML que dispara la descarga del archivo sin requerir un click del usuario.

    Se inyecta via st.components.v1.html: crea un enlace <a download> con el
    archivo codificado en base64 y lo clickea programaticamente con JS. Sirve
    como señal inequivoca de que el estudio culmino, sin depender de que el
    usuario note y presione el boton de descarga manual.
    """
    b64 = base64.b64encode(file_bytes).decode("ascii")
    safe_filename = filename.replace('"', "")
    return (
        f'<a id="sivml_auto_dl" href="data:{mime};base64,{b64}" '
        f'download="{safe_filename}" style="display:none"></a>'
        '<script>document.getElementById("sivml_auto_dl").click();</script>'
    )
