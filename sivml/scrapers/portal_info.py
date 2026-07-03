"""
Información estática sobre portales de empleo.
Este módulo NO importa nada del paquete scrapers ni de ningún módulo del proyecto,
de modo que siempre puede importarse sin riesgo de errores en cadena.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Estado operacional validado (junio 2026)
# ---------------------------------------------------------------------------

PORTAL_STATUS: dict[str, dict] = {
    "computrabajo": {
        "status": "OPERACIONAL",
        "nota": "20 resultados por página. Título, empresa, ciudad y salario funcionales. Recomendado.",
    },
    "indeed": {
        "status": "PARCIAL",
        "nota": (
            "Funciona para el primer keyword de cada sesión. "
            "Indeed activa detección de bots después de la primera búsqueda exitosa. "
            "Workaround: usar máx. 1 keyword por estudio cuando se incluye Indeed."
        ),
    },
    "bumeran": {
        "status": "PARCIAL",
        "nota": (
            "Extrae título, empresa y ciudad correctamente (selectores validados). "
            "La búsqueda puede mostrar resultados destacados en lugar de filtrados por keyword. "
            "Verificar manualmente la relevancia de los resultados."
        ),
    },
    "laborum": {
        "status": "NO_OPERACIONAL",
        "nota": (
            "VALIDADO junio 2026: 0 resultados en prueba real. "
            "laborum.pe usa React client-side con MUI, el contenido no es scrapeble. "
            "Excluido automaticamente del scraping."
        ),
    },
    "jooble": {
        "status": "NO_OPERACIONAL",
        "nota": (
            "VALIDADO junio 2026: 0 resultados sin API key. "
            "Bloquea acceso HTML directo (403). Para activar: JOOBLE_API_KEY en .env. "
            "Excluido automaticamente del scraping sin API key."
        ),
    },
    "linkedin": {
        "status": "PARCIAL",
        "nota": (
            "Protecciones anti-bot agresivas. "
            "Funciona para búsquedas públicas sin login, con delays conservadores. "
            "Volumen bajo comparado con portales dedicados."
        ),
    },
}

# ---------------------------------------------------------------------------
# Capacidades detalladas de cada portal
# ---------------------------------------------------------------------------

PORTAL_CAPABILITIES: dict[str, dict] = {
    "computrabajo": {
        "uso_simultaneo":   True,
        "nota_simultaneo":  "Se puede combinar con cualquier otro portal.",
        "max_keywords":     "Sin límite conocido por sesión.",
        "paginacion":       "Hasta 50 páginas por búsqueda (configurable con max_pages).",
        "anti_bot":         "Bajo. Requiere user-agent real. Sin captcha frecuente.",
        "delay_recomendado": "2–5 s entre peticiones.",
        "campos_disponibles": ["título", "empresa", "ciudad", "salario", "descripción"],
        "requiere_login":   False,
        "cobertura":        "Perú — amplia. Más de 10 000 ofertas activas.",
    },
    "indeed": {
        "uso_simultaneo":   False,
        "nota_simultaneo":  (
            "NO combinar con otras búsquedas en la misma sesión de Playwright. "
            "Indeed bloquea después de la primera búsqueda exitosa por sesión. "
            "Si se usa, ponerlo solo y con 1 keyword."
        ),
        "max_keywords":     "1 por sesión de navegador. Reiniciar navegador para más.",
        "paginacion":       "Offsets de 15. Hasta ~10 páginas antes de detección.",
        "anti_bot":         "Alto. Detecta bots por velocidad, fingerprinting y cookies.",
        "delay_recomendado": "5–10 s entre peticiones.",
        "campos_disponibles": ["título", "empresa", "ciudad", "descripción"],
        "requiere_login":   False,
        "cobertura":        "Perú — moderada. ~500–2000 ofertas activas.",
    },
    "bumeran": {
        "uso_simultaneo":   True,
        "nota_simultaneo":  "Combinar con computrabajo es seguro.",
        "max_keywords":     "Sin límite técnico, pero el filtrado de keywords puede ser inexacto.",
        "paginacion":       "Paginación por parámetro ?page=N.",
        "anti_bot":         "Medio. Requiere esperar a que React hidrate el DOM.",
        "delay_recomendado": "2–4 s entre peticiones.",
        "campos_disponibles": ["título", "empresa", "ciudad", "modalidad"],
        "requiere_login":   False,
        "cobertura":        "Perú — moderada. App React puede mostrar resultados destacados.",
    },
    "laborum": {
        "uso_simultaneo":   False,
        "nota_simultaneo":  "No operacional — no incluir en estudios.",
        "max_keywords":     "N/A",
        "paginacion":       "N/A",
        "anti_bot":         "N/A — el sitio no retorna datos scrapeables.",
        "delay_recomendado": "N/A",
        "campos_disponibles": [],
        "requiere_login":   False,
        "cobertura":        "No operacional actualmente.",
    },
    "jooble": {
        "uso_simultaneo":   True,
        "nota_simultaneo":  "Con API key: combinar con cualquier portal. Sin API key: 0 resultados.",
        "max_keywords":     "Sin límite por la API oficial.",
        "paginacion":       "Paginación por parámetro 'page' en la API.",
        "anti_bot":         "N/A — acceso vía API oficial.",
        "delay_recomendado": "1–2 s (límite de API).",
        "campos_disponibles": ["título", "empresa", "ciudad", "salario", "descripción (snippet)"],
        "requiere_login":   True,
        "cobertura":        "Internacional. Agrega resultados de múltiples portales.",
    },
    "linkedin": {
        "uso_simultaneo":   False,
        "nota_simultaneo":  "Usar solo, con delays altos. No combinar con Indeed en la misma sesión.",
        "max_keywords":     "1–2 por sesión antes de posible detección.",
        "paginacion":       "Offsets de 25. Máx. ~5 páginas sin login.",
        "anti_bot":         "Muy alto. Fingerprinting avanzado, requiere cookies de sesión para volúmenes altos.",
        "delay_recomendado": "5–15 s entre peticiones.",
        "campos_disponibles": ["título", "empresa", "ciudad", "modalidad", "contrato", "descripción"],
        "requiere_login":   False,
        "cobertura":        "Internacional. Alta calidad pero bajo volumen sin login.",
    },
}

RECOMMENDED_PORTALS: list[str] = ["computrabajo", "bumeran"]

# Portales que producen resultados reales (validado junio 2026)
ACTIVE_PORTALS: list[str] = ["computrabajo", "indeed", "bumeran", "linkedin"]

# Portales que NO funcionan actualmente (excluidos automaticamente del scraping)
INACTIVE_PORTALS: list[str] = ["laborum", "jooble"]

# Combinaciones seguras para uso simultaneo
SAFE_COMBINATIONS: list[list[str]] = [
    ["computrabajo"],
    ["bumeran"],
    ["computrabajo", "bumeran"],
    ["indeed"],   # indeed siempre solo (detecta bots si se combina)
    ["linkedin"], # linkedin siempre solo
]
