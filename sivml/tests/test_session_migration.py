"""
Base.metadata.create_all() solo crea tablas NUEVAS -- nunca agrega columnas
a una tabla que ya existe. Si el usuario ya tiene un sivml.db real con
estudios guardados y el modelo Study gana una columna nueva (stop_requested),
init_db() por si solo la ignoraria silenciosamente para tablas preexistentes.
_run_lightweight_migrations() agrega columnas faltantes sin destruir datos.
"""
from sqlalchemy import create_engine, inspect, text

from database.session import Base, _run_lightweight_migrations
import database.models  # noqa: F401 -- registra los modelos en Base.metadata


def _make_old_schema_engine():
    """Simula un sivml.db real creado ANTES de que existiera stop_requested."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE studies (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                academic_program VARCHAR(255),
                config_yaml TEXT,
                started_at DATETIME,
                finished_at DATETIME,
                status VARCHAR(20)
            )
        """))
        conn.execute(text(
            "INSERT INTO studies (id, name, status) VALUES ('s1', 'Estudio Real Existente', 'completed')"
        ))
    return engine


class TestLightweightMigrations:
    def test_adds_missing_column_to_existing_table(self):
        engine = _make_old_schema_engine()
        _run_lightweight_migrations(engine)
        cols = {c["name"] for c in inspect(engine).get_columns("studies")}
        assert "stop_requested" in cols

    def test_does_not_lose_existing_data(self):
        engine = _make_old_schema_engine()
        _run_lightweight_migrations(engine)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT id, name, status FROM studies WHERE id='s1'")).fetchone()
        assert row is not None
        assert row[1] == "Estudio Real Existente"
        assert row[2] == "completed"

    def test_new_column_defaults_to_false_for_existing_rows(self):
        engine = _make_old_schema_engine()
        _run_lightweight_migrations(engine)
        with engine.connect() as conn:
            value = conn.execute(text("SELECT stop_requested FROM studies WHERE id='s1'")).scalar()
        assert value in (0, False)

    def test_safe_to_run_twice(self):
        engine = _make_old_schema_engine()
        _run_lightweight_migrations(engine)
        _run_lightweight_migrations(engine)  # no debe fallar si la columna ya existe
        cols = {c["name"] for c in inspect(engine).get_columns("studies")}
        assert "stop_requested" in cols

    def test_no_op_on_fresh_schema_already_current(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)  # ya incluye stop_requested desde el modelo actual
        _run_lightweight_migrations(engine)  # no debe fallar
        cols = {c["name"] for c in inspect(engine).get_columns("studies")}
        assert "stop_requested" in cols

    def test_no_op_if_studies_table_does_not_exist_yet(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        _run_lightweight_migrations(engine)  # no debe fallar sobre una DB vacia
