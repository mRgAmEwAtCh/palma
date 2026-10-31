from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProxmoxSourceBase(SQLModel):
    name: str = Field(index=True, unique=True)
    url: str  # e.g. https://pve1.lan:8006
    token_id: str  # e.g. root@pam!homelab
    verify_ssl: bool = False
    default_ssh_user: str = "root"


class ProxmoxSource(ProxmoxSourceBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    token_secret: str
    last_sync: datetime | None = None


class ProxmoxSourceCreate(ProxmoxSourceBase):
    token_secret: str


class ProxmoxSourceUpdate(SQLModel):
    name: str | None = None
    url: str | None = None
    token_id: str | None = None
    token_secret: str | None = None
    verify_ssl: bool | None = None
    default_ssh_user: str | None = None


class ProxmoxSourceRead(ProxmoxSourceBase):
    id: int
    last_sync: datetime | None = None


class HostBase(SQLModel):
    name: str = Field(index=True, unique=True)
    address: str
    port: int = 22
    ssh_user: str | None = None
    kind: str = "lxc"  # lxc | vm | baremetal | other
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    vars: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = True
    notes: str = ""


class Host(HostBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    source: str = "manual"  # manual | proxmox
    proxmox_source_id: int | None = Field(default=None, foreign_key="proxmoxsource.id")
    proxmox_node: str | None = None
    proxmox_vmid: int | None = None
    proxmox_type: str | None = None  # lxc | qemu
    proxmox_status: str | None = None
    os_family: str | None = None
    os_name: str | None = None
    os_version: str | None = None
    last_seen: datetime | None = None
    last_error: str | None = None
    health: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    health_checked_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class HostCreate(HostBase):
    pass


class HostUpdate(SQLModel):
    name: str | None = None
    address: str | None = None
    port: int | None = None
    ssh_user: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    vars: dict[str, Any] | None = None
    enabled: bool | None = None
    notes: str | None = None


class HostRead(HostBase):
    id: int
    source: str
    proxmox_source_id: int | None
    proxmox_node: str | None
    proxmox_vmid: int | None
    proxmox_type: str | None
    proxmox_status: str | None
    os_family: str | None
    os_name: str | None
    os_version: str | None
    last_seen: datetime | None
    last_error: str | None
    health: dict[str, Any] | None
    health_checked_at: datetime | None


class Run(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    playbook: str
    status: str = "pending"  # pending | running | successful | failed | canceled | error
    check_mode: bool = False
    extra_vars: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    host_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    host_names: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    stats: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    rc: int | None = None
    triggered_by: str | None = None
    schedule_id: int | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunCreate(SQLModel):
    playbook: str
    host_ids: list[int]
    check_mode: bool = False
    extra_vars: dict[str, Any] = Field(default_factory=dict)


class ScheduleBase(SQLModel):
    name: str
    playbook: str
    cron: str
    enabled: bool = True
    # Target resolved at run time: explicit hosts, else hosts matching any tag/type, else all enabled hosts.
    target_host_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    target_tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    extra_vars: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Schedule(ScheduleBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    last_run_id: int | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(SQLModel):
    name: str | None = None
    playbook: str | None = None
    cron: str | None = None
    enabled: bool | None = None
    target_host_ids: list[int] | None = None
    target_tags: list[str] | None = None
    extra_vars: dict[str, Any] | None = None
