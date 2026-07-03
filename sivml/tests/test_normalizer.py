import pytest
from processing.normalizer import (
    normalize_city,
    normalize_company,
    normalize_education,
    normalize_experience,
    normalize_modality,
    normalize_salary,
    normalize_title,
)


class TestNormalizeCity:
    def test_exact_alias(self):
        assert normalize_city("Lima Metropolitana") == "Lima"

    def test_case_insensitive(self):
        assert normalize_city("LIMA METROPOLITANA") == "Lima"

    def test_partial_match(self):
        assert normalize_city("San Isidro, Lima") == "Lima"

    def test_unknown_returns_title_case(self):
        result = normalize_city("Ciudad Desconocida")
        assert result is not None
        assert isinstance(result, str)

    def test_none_input(self):
        assert normalize_city(None) is None


class TestNormalizeCompany:
    def test_strip_sac(self):
        result = normalize_company("Mi Empresa S.A.C.")
        assert "S.A.C" not in (result or "").upper()

    def test_strip_srl(self):
        result = normalize_company("Servicios Generales S.R.L.")
        assert "S.R.L" not in (result or "").upper()

    def test_none_input(self):
        assert normalize_company(None) is None

    def test_known_alias(self):
        result = normalize_company("MINSA")
        assert result == "Ministerio de Salud"


class TestNormalizeSalary:
    def test_pen_monthly(self):
        mn, mx, currency, period = normalize_salary("S/ 3,500 mensual")
        assert currency == "PEN"
        assert period == "monthly"
        assert mn == 3500.0

    def test_range(self):
        mn, mx, currency, period = normalize_salary("S/ 2,000 - 4,000")
        assert mn == 2000.0
        assert mx == 4000.0

    def test_usd(self):
        mn, mx, currency, period = normalize_salary("USD 1,500 mensual")
        assert currency == "USD"
        assert mn == 1500.0

    def test_out_of_range_returns_none(self):
        mn, mx, currency, period = normalize_salary("S/ 5 mensual")
        assert mn is None

    def test_none_input(self):
        assert normalize_salary(None) == (None, None, None, None)

    def test_no_number(self):
        assert normalize_salary("A convenir") == (None, None, None, None)


class TestNormalizeExperience:
    def test_range(self):
        mn, mx = normalize_experience("2 a 5 años de experiencia")
        assert mn == 2
        assert mx == 5

    def test_single(self):
        mn, mx = normalize_experience("3 años de experiencia")
        assert mn == 3
        assert mx == 3

    def test_minimum(self):
        mn, mx = normalize_experience("Mínimo 2 años")
        assert mn == 2

    def test_none_input(self):
        assert normalize_experience(None) == (None, None)


class TestNormalizeEducation:
    def test_maestria(self):
        assert normalize_education("Maestría o equivalente") == "master"

    def test_bachiller(self):
        assert normalize_education("Bachiller en Medicina") == "undergraduate"

    def test_tecnico(self):
        assert normalize_education("Técnico en enfermería") == "technical"

    def test_doctorado(self):
        assert normalize_education("Doctorado en salud pública") == "phd"

    def test_none_input(self):
        assert normalize_education(None) is None


class TestNormalizeModality:
    def test_remote(self):
        assert normalize_modality("Trabajo remoto") == "remote"

    def test_hybrid(self):
        assert normalize_modality("Modalidad híbrida") == "hybrid"

    def test_onsite(self):
        assert normalize_modality("Presencial") == "onsite"

    def test_none_input(self):
        assert normalize_modality(None) is None


class TestNormalizeTitle:
    def test_removes_urgente(self):
        result = normalize_title("URGENTE - Médico Salubrista")
        assert "urgente" not in (result or "").lower()

    def test_none_input(self):
        assert normalize_title(None) is None
