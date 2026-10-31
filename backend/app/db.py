from collections.abc import Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()
_settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{_settings.data_dir / 'app.db'}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Minimal forward migration: adds new nullable columns to existing tables (create_all does not)."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing and column.nullable:
                    col_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
