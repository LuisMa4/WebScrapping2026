from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup


def strip_html(text: str | None) -> str | None:
    if not text:
        return None
    soup = BeautifulSoup(text, "lxml")
    return soup.get_text(separator=" ", strip=True)


def normalize_whitespace(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_encoding(text: str | None) -> str | None:
    if not text:
        return None
    return unicodedata.normalize("NFC", text)


def clean_text(text: str | None) -> str | None:
    """Limpieza completa: HTML -> encoding -> whitespace (una sola linea)."""
    return normalize_whitespace(normalize_encoding(strip_html(text)))


def clean_description(raw: str | None, max_chars: int = 5000) -> str | None:
    """
    Limpia la descripcion preservando la estructura de parrafos y bullets.
    A diferencia de clean_text, mantiene saltos de linea entre secciones
    para que _extract_requirements pueda identificar encabezados.
    """
    if not raw:
        return None

    # Si el raw ya es texto plano (sin etiquetas HTML)
    if "<" not in raw:
        text = raw
    else:
        soup = BeautifulSoup(raw, "lxml")
        # Insertar saltos de linea antes de elementos de bloque
        for tag in soup.find_all(["p", "br", "li", "h1", "h2", "h3", "h4", "div"]):
            tag.insert_before("\n")
        text = soup.get_text(separator=" ")

    text = unicodedata.normalize("NFC", text)
    # Colapsar espacios horizontales pero preservar saltos de linea
    text = re.sub(r"[ \t]+", " ", text)
    # Max 2 saltos de linea consecutivos
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Restaurar bullets: "- texto" al inicio de linea
    text = re.sub(r"\n\s*[-•*]\s*", "\n- ", text)
    text = text.strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text if text else None
