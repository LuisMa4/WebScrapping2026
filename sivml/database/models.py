from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.session import Base


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    academic_program: Mapped[str | None] = mapped_column(String(255))
    config_yaml: Mapped[str | None] = mapped_column(Text)  # snapshot completo del YAML
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|completed|failed|stopped
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    raw_jobs: Mapped[list[RawJob]] = relationship("RawJob", back_populates="study")
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="study")
    scraping_runs: Mapped[list[ScrapingRun]] = relationship("ScrapingRun", back_populates="study")


class RawJob(Base):
    """Una fila por oferta tal como fue scrapeada. Inmutable después de insertar."""
    __tablename__ = "raw_jobs"
    # Unicidad por ESTUDIO: la misma oferta (portal+source_id) puede aparecer en
    # distintos estudios (ej. plantillas re-ejecutadas periodicamente) sin perderse.
    # Solo previene duplicados dentro de un mismo estudio (ej. re-correr el mismo scrape).
    __table_args__ = (
        UniqueConstraint("study_id", "portal", "source_id", name="uq_raw_jobs_study_portal_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_id: Mapped[str] = mapped_column(String(36), ForeignKey("studies.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    portal: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    title: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(100))
    posted_date: Mapped[date | None] = mapped_column(Date)

    description_raw: Mapped[str | None] = mapped_column(Text)
    salary_raw: Mapped[str | None] = mapped_column(String(255))
    modality_raw: Mapped[str | None] = mapped_column(String(100))
    contract_raw: Mapped[str | None] = mapped_column(String(100))
    experience_raw: Mapped[str | None] = mapped_column(String(255))
    education_raw: Mapped[str | None] = mapped_column(String(255))
    keyword_matched: Mapped[str | None] = mapped_column(String(255))

    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    canonical_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("jobs.id"))

    study: Mapped[Study] = relationship("Study", back_populates="raw_jobs")
    canonical_job: Mapped[Job | None] = relationship("Job", foreign_keys=[canonical_id])


class Job(Base):
    """Oferta deduplicada y normalizada. Tabla principal de análisis."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_id: Mapped[str] = mapped_column(String(36), ForeignKey("studies.id"), nullable=False)

    title_normalized: Mapped[str | None] = mapped_column(Text)
    company_normalized: Mapped[str | None] = mapped_column(String(255))
    city_normalized: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(100))

    portal: Mapped[str | None] = mapped_column(String(50))  # primer portal donde apareció
    url: Mapped[str | None] = mapped_column(Text)
    posted_date: Mapped[date | None] = mapped_column(Date)

    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(10))
    salary_period: Mapped[str | None] = mapped_column(String(20))  # monthly|annual|hourly

    modality: Mapped[str | None] = mapped_column(String(50))       # remote|hybrid|onsite
    contract_type: Mapped[str | None] = mapped_column(String(100))
    experience_years_min: Mapped[int | None] = mapped_column(Integer)
    experience_years_max: Mapped[int | None] = mapped_column(Integer)
    education_level: Mapped[str | None] = mapped_column(String(50))

    description_clean: Mapped[str | None] = mapped_column(Text)

    _raw_job_ids_json: Mapped[str | None] = mapped_column("raw_job_ids", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    study: Mapped[Study] = relationship("Study", back_populates="jobs")

    @property
    def raw_job_ids(self) -> list[int]:
        if self._raw_job_ids_json:
            return json.loads(self._raw_job_ids_json)
        return []

    @raw_job_ids.setter
    def raw_job_ids(self, ids: list[int]) -> None:
        self._raw_job_ids_json = json.dumps(ids)


class StudyTemplate(Base):
    """Plantilla reutilizable de configuracion de scraping (sin fechas)."""
    __tablename__ = "study_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    academic_program: Mapped[str] = mapped_column(String(255), nullable=False)

    keywords_json: Mapped[str] = mapped_column(Text, nullable=False)
    cities_json: Mapped[str] = mapped_column(Text, nullable=False)
    portals_json: Mapped[str] = mapped_column(Text, nullable=False)

    max_pages: Mapped[int] = mapped_column(Integer, default=10)
    delay_min: Mapped[float] = mapped_column(Float, default=2.0)
    delay_max: Mapped[float] = mapped_column(Float, default=5.0)
    headless: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    run_count: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def keywords(self) -> list[str]:
        return json.loads(self.keywords_json)

    @keywords.setter
    def keywords(self, value: list[str]) -> None:
        self.keywords_json = json.dumps(value, ensure_ascii=False)

    @property
    def cities(self) -> list[str]:
        return json.loads(self.cities_json)

    @cities.setter
    def cities(self, value: list[str]) -> None:
        self.cities_json = json.dumps(value, ensure_ascii=False)

    @property
    def portals(self) -> list[str]:
        return json.loads(self.portals_json)

    @portals.setter
    def portals(self, value: list[str]) -> None:
        self.portals_json = json.dumps(value, ensure_ascii=False)


class ScrapingRun(Base):
    """Log de observabilidad por portal/keyword/ciudad."""
    __tablename__ = "scraping_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_id: Mapped[str] = mapped_column(String(36), ForeignKey("studies.id"), nullable=False)
    portal: Mapped[str] = mapped_column(String(50), nullable=False)
    keyword: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    records_new: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    error_message: Mapped[str | None] = mapped_column(Text)

    study: Mapped[Study] = relationship("Study", back_populates="scraping_runs")
