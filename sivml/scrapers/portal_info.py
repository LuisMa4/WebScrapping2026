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
            "Funciona correctamente combinado con otros portales y con varios "
            "keywords: cada búsqueda keyword+ciudad usa un contexto de navegador "
            "nuevo (cookies limpias), lo que evita la detección de bots que antes "
            "obligaba a usarlo solo. Validado en vivo julio 2026 junto a "
            "computrabajo, bumeran y linkedin simultáneamente."
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
            "Protecciones anti-bot agresivas, pero el mismo contexto fresco por "
            "keyword+ciudad que usa Indeed permite combinarlo de forma segura con "
            "otros portales (validado en vivo julio 2026). Funciona para búsquedas "
            "públicas sin login, con delays conservadores. Volumen y precisión "
            "menores que portales dedicados."
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
        "uso_simultaneo":   True,
        "nota_simultaneo":  (
            "Seguro combinarlo con cualquier otro portal: SIVML le da un contexto "
            "de navegador nuevo por cada keyword+ciudad (fresh_context_per_keyword), "
            "evitando la detección de bots que antes forzaba a usarlo solo."
        ),
        "max_keywords":     "Sin límite — cada uno corre en su propio contexto fresco.",
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
        "uso_simultaneo":   True,
        "nota_simultaneo":  (
            "Seguro combinarlo con otros portales (incluido Indeed) gracias al "
            "contexto de navegador fresco por keyword+ciudad."
        ),
        "max_keywords":     "Sin límite técnico — cada uno corre en su propio contexto fresco.",
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

# Combinaciones seguras para uso simultaneo. Desde que Indeed y LinkedIn usan
# contexto de navegador fresco por keyword+ciudad (fresh_context_per_keyword),
# los 4 portales activos se pueden combinar entre si sin problema -- validado
# en vivo julio 2026 corriendo los 4 juntos en paralelo.
SAFE_COMBINATIONS: list[list[str]] = [
    ["computrabajo"],
    ["bumeran"],
    ["indeed"],
    ["linkedin"],
    ["computrabajo", "bumeran"],
    ["computrabajo", "indeed"],
    ["computrabajo", "linkedin"],
    ["computrabajo", "bumeran", "indeed", "linkedin"],
]
