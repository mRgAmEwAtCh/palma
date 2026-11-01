from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlmodel import Field, Session, SQLModel

from .auth import current_user
from .db import get_session

Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Background = Literal["graphite", "midnight", "slate", "forest"]


class ThemeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary: Color = "#f4a63c"
    secondary: Color = "#3fb950"
    background: Background = "graphite"


class SystemTheme(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    primary: str
    secondary: str
    background: str


PRESETS = [
    {"id": "graphite", "name": "Graphite (default)", "bg": "#0a0a0a", "surface": "#161616",
     "surface2": "#202020", "border": "#2e2e2e", "text": "#ececec", "muted": "#9c9c9c"},
    {"id": "midnight", "name": "Midnight", "bg": "#090e1a", "surface": "#131b2b",
     "surface2": "#1c273b", "border": "#34435a", "text": "#edf2fa", "muted": "#a3b1c7"},
    {"id": "slate", "name": "Slate", "bg": "#171b20", "surface": "#222830",
     "surface2": "#2c343e", "border": "#45515f", "text": "#f0f3f7", "muted": "#b0bac6"},
    {"id": "forest", "name": "Forest", "bg": "#0b1410", "surface": "#15221b",
     "surface2": "#203128", "border": "#3a5143", "text": "#ecf5ef", "muted": "#a5baad"},
]

router = APIRouter(prefix="/api/theme", tags=["theme"])


@router.get("")
def get_theme(s: Session = Depends(get_session)):
    stored = s.get(SystemTheme, 1)
    return {
        "theme": ThemeSettings.model_validate(stored, from_attributes=True) if stored else ThemeSettings(),
        "defaults": ThemeSettings(),
        "presets": PRESETS,
    }


@router.put("", response_model=ThemeSettings, dependencies=[Depends(current_user)])
def save_theme(body: ThemeSettings, s: Session = Depends(get_session)):
    stored = s.get(SystemTheme, 1) or SystemTheme(**body.model_dump())
    stored.sqlmodel_update(body.model_dump())
    s.add(stored)
    s.commit()
    s.refresh(stored)
    return ThemeSettings.model_validate(stored, from_attributes=True)


@router.delete("", response_model=ThemeSettings, dependencies=[Depends(current_user)])
def reset_theme(s: Session = Depends(get_session)):
    stored = s.get(SystemTheme, 1)
    if stored:
        s.delete(stored)
        s.commit()
    return ThemeSettings()
