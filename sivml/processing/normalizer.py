from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from processing.cleaner import clean_text

# ---------------------------------------------------------------------------
# Carga de tablas de alias
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_aliases(filename: str) -> dict[str, str]:
    path = _CONFIG_DIR / filename
    if not path.exists():
        return {}
    raw: dict = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k.lower().strip(): v for k, v in raw.items()}


_CITY_ALIASES: dict[str, str] = {}
_COMPANY_ALIASES: dict[str, str] = {}


def _ensure_loaded() -> None:
    global _CITY_ALIASES, _COMPANY_ALIASES
    if not _CITY_ALIASES:
        _CITY_ALIASES = _load_aliases("city_aliases.yaml")
    if not _COMPANY_ALIASES:
        _COMPANY_ALIASES = _load_aliases("company_aliases.yaml")


# ---------------------------------------------------------------------------
# Sufijos legales a eliminar antes de normalizar empresa
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = re.compile(
    r"\b(s\.?\s*a\.?\s*c\.?|s\.?\s*r\.?\s*l\.?|s\.?\s*a\.?|e\.?\s*i\.?\s*r\.?\s*l\.?|"
    r"inc\.?|ltd\.?|llc\.?|sas\.?|s\.?\s*p\.?\s*a\.?)\s*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Normalización de ciudad
# ---------------------------------------------------------------------------

_NORMALIZATION_WARNINGS: list[str] = []


def normalize_city(raw: str | None) -> str | None:
    if not raw:
        return None
    _ensure_loaded()
    key = clean_text(raw) or ""
    key = key.lower().strip()
    if key in _CITY_ALIASES:
        return _CITY_ALIASES[key]
    # Búsqueda parcial (el raw puede contener ciudad + región)
    for alias, canonical in _CITY_ALIASES.items():
        if alias in key:
            return canonical
    _NORMALIZATION_WARNINGS.append(f"ciudad desconocida: {raw!r}")
    return raw.strip().title()


def normalize_company(raw: str | None) -> str | None:
    if not raw:
        return None
    _ensure_loaded()
    cleaned = (clean_text(raw) or "").strip()
    # Quitar sufijos legales
    cleaned_no_suffix = _LEGAL_SUFFIXES.sub("", cleaned).strip(" .,")
    key = cleaned_no_suffix.lower()
    if key in _COMPANY_ALIASES:
        return _COMPANY_ALIASES[key]
    return cleaned_no_suffix.title() if cleaned_no_suffix else cleaned.title()


# ---------------------------------------------------------------------------
# Normalización de salario
# ---------------------------------------------------------------------------

_CURRENCIES = {
    "s/": "PEN", "sol": "PEN", "soles": "PEN", "pen": "PEN",
    "usd": "USD", "$": "USD", "us$": "USD", "dólar": "USD", "dolares": "USD",
    "clp": "CLP", "cop": "COP", "ars": "ARS", "mxn": "MXN",
}

_PERIOD_PATTERNS = [
    (r"hora|hr\b|h\b", "hourly"),
    (r"día|diario|dia", "daily"),
    (r"semana|semanal", "weekly"),
    (r"mes|mensual|monthly|al\s+mes", "monthly"),
    (r"año|anual|annual", "annual"),
]

_NUMBER_RE = re.compile(r"[\d,\.]+")


def _parse_number(s: str) -> float | None:
    """
    Parsea un numero en formato americano (1,200.00) o europeo (1.200,00).
    Computrabajo Peru usa formato europeo: punto = miles, coma = decimal.
    """
    s = s.strip()
    if "," in s and "." in s:
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_comma > last_dot:
            # Europeo: 1.200,00 -> 1200.00
            s = s.replace(".", "").replace(",", ".")
        else:
            # Americano: 1,200.00 -> 1200.00
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            # Decimal: 1200,50 -> 1200.50
            s = s.replace(",", ".")
        else:
            # Miles: 1,200 -> 1200
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_salary(
    raw: str | None,
) -> tuple[float | None, float | None, str | None, str | None]:
    """
    Devuelve (salary_min, salary_max, currency, period).
    Todos los valores None si no se puede parsear.
    """
    if not raw:
        return None, None, None, None

    text = (clean_text(raw) or "").lower()

    # Detectar moneda
    currency = "PEN"
    for symbol, code in _CURRENCIES.items():
        if symbol in text:
            currency = code
            break

    # Detectar período
    period = "monthly"
    for pattern, label in _PERIOD_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            period = label
            break

    # Extraer números
    numbers = [_parse_number(m) for m in _NUMBER_RE.findall(text)]
    numbers = [n for n in numbers if n is not None and n > 0]

    if not numbers:
        return None, None, None, None

    salary_min = min(numbers)
    salary_max = max(numbers) if len(numbers) > 1 else salary_min

    # Sanidad: mensual en PEN entre 100 y 50,000 (salario max Peru ~S/50k)
    if period == "monthly" and currency == "PEN":
        if salary_min < 100 or salary_max >= 50_000:
            return None, None, None, None

    return salary_min, salary_max, currency, period


# ---------------------------------------------------------------------------
# Normalización de experiencia
# ---------------------------------------------------------------------------

_EXP_PATTERNS = [
    re.compile(r"(\d+)\s*(?:a|–|-)\s*(\d+)\s*años?", re.IGNORECASE),
    re.compile(r"(\d+)\s*\+?\s*años?\s*(?:de\s*)?experiencia", re.IGNORECASE),
    re.compile(r"mínimo\s*(\d+)\s*años?", re.IGNORECASE),
    re.compile(r"(\d+)\s*años?\s*(?:de\s*)?(?:experiencia|exp\.?)", re.IGNORECASE),
]


def normalize_experience(raw: str | None) -> tuple[int | None, int | None]:
    """Devuelve (years_min, years_max)."""
    if not raw:
        return None, None

    text = clean_text(raw) or ""

    # Patrón rango: "2 a 5 años" o "2-5 años"
    m = re.search(r"(\d+)\s*(?:a|–|-)\s*(\d+)\s*años?", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Patrón único: "3 años de experiencia"
    for pat in _EXP_PATTERNS[1:]:
        m = pat.search(text)
        if m:
            years = int(m.group(1))
            return years, years

    return None, None


# ---------------------------------------------------------------------------
# Normalización de nivel educativo
# ---------------------------------------------------------------------------

_EDU_MAP = [
    (r"doctorado|phd|ph\.d", "phd"),
    (r"maestría|magíster|magister|mba|máster|master", "master"),
    (r"titulado|licenciado|profesional|ingeniero|médico", "bachelor"),
    (r"bachiller|egresado|técnico\s+universitario", "undergraduate"),
    (r"técnico|tecnico|instituto", "technical"),
    (r"secundaria|bachillerato|high\s*school", "highschool"),
]


def normalize_education(raw: str | None) -> str | None:
    if not raw:
        return None
    text = (clean_text(raw) or "").lower()
    for pattern, level in _EDU_MAP:
        if re.search(pattern, text, re.IGNORECASE):
            return level
    return None


# ---------------------------------------------------------------------------
# Normalización de modalidad
# ---------------------------------------------------------------------------

_MODALITY_MAP = [
    (r"remoto|teletrabajo|home\s*office|virtual|a\s*distancia", "remote"),
    (r"híbrid[oa]?|hibrido|hibrida|hybrid|semi.?presencial", "hybrid"),
    (r"presencial|on.?site|in.?office", "onsite"),
]


def normalize_modality(raw: str | None) -> str | None:
    if not raw:
        return None
    text = (clean_text(raw) or "").lower()
    for pattern, label in _MODALITY_MAP:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return None


# ---------------------------------------------------------------------------
# Normalización de título
# ---------------------------------------------------------------------------

_TITLE_NOISE = re.compile(
    r"\b(se\s*busca|urgente|plaza\s*libre|oportunidad|convocatoria|"
    r"vacante|oferta\s*laboral|nuevo|!+|\*+)\b",
    re.IGNORECASE,
)


def normalize_title(raw: str | None) -> str | None:
    if not raw:
        return None
    text = clean_text(raw) or ""
    text = _TITLE_NOISE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -–|/\\")
    return text.title() if text else None


def get_normalization_warnings() -> list[str]:
    return list(_NORMALIZATION_WARNINGS)
