from datetime import datetime, UTC

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, String
from sqlalchemy.orm import relationship

from app.db import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    product_idea = Column(Text, nullable=False)
    excluded_scope = Column(Text, nullable=False)
    completion_contract = Column(Text, nullable=False)
    root_path = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    capabilities = relationship("Capability", back_populates="project", cascade="all, delete-orphan")


class Capability(Base):
    __tablename__ = "capabilities"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    outcome = Column(Text, nullable=False)
    acceptance_criteria = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    project = relationship("Project", back_populates="capabilities")
    mandates = relationship("Mandate", back_populates="capability", cascade="all, delete-orphan")


class Mandate(Base):
    __tablename__ = "mandates"

    id = Column(Integer, primary_key=True, index=True)
    capability_id = Column(Integer, ForeignKey("capabilities.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    objective = Column(Text, nullable=False)
    work_items_json = Column(Text, nullable=False)
    evidence_summary = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    capability = relationship("Capability", back_populates="mandates")


class WorkLog(Base):
    __tablename__ = "work_logs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    ts = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    source = Column(String(64), nullable=False, default="manual")
    command_text = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)

    project = relationship("Project")


class FileTreeEntry(Base):
    __tablename__ = "file_tree_entries"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    path = Column(Text, nullable=False)
    entry_type = Column(String(16), nullable=False)
    sha256 = Column(String(64), nullable=True)
    last_seen_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    project = relationship("Project")


class FileSnapshot(Base):
    __tablename__ = "file_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    path = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    content_text = Column(Text, nullable=False)
    captured_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))

    project = relationship("Project")
