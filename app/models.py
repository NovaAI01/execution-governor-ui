from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base


def utc_now():
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    product_idea = Column(Text, nullable=False)
    excluded_scope = Column(Text, nullable=False)
    completion_contract = Column(Text, nullable=False)
    root_path = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    capabilities = relationship(
        "Capability",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    scope_bindings = relationship(
        "ScopeBinding",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    observation_runs = relationship(
        "ObservationRun",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    observation_diffs = relationship(
        "ObservationDiff",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    governor_checks = relationship(
        "GovernorCheck",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    project_events = relationship(
        "ProjectEvent",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    overview_states = relationship(
        "OverviewState",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    architecture_states = relationship(
        "ArchitectureState",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    diff_states = relationship(
        "DiffState",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    governor_states = relationship(
        "GovernorState",
        back_populates="project",
        cascade="all, delete-orphan",
    )


class Capability(Base):
    __tablename__ = "capabilities"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    outcome = Column(Text, nullable=False)
    acceptance_criteria = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    created_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="capabilities")
    mandates = relationship(
        "Mandate",
        back_populates="capability",
        cascade="all, delete-orphan",
    )


class Mandate(Base):
    __tablename__ = "mandates"

    id = Column(Integer, primary_key=True, index=True)
    capability_id = Column(Integer, ForeignKey("capabilities.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    objective = Column(Text, nullable=False)
    work_items_json = Column(Text, nullable=False)
    evidence_summary = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    created_at = Column(DateTime, nullable=False, default=utc_now)

    capability = relationship("Capability", back_populates="mandates")


class ScopeBinding(Base):
    __tablename__ = "scope_bindings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    binding_name = Column(String(255), nullable=False)
    included_paths_json = Column(Text, nullable=False, default="[]")
    excluded_paths_json = Column(Text, nullable=False, default="[]")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="scope_bindings")
    governor_checks = relationship(
        "GovernorCheck",
        back_populates="scope_binding",
    )


class WorkLog(Base):
    __tablename__ = "work_logs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    ts = Column(DateTime, nullable=False, default=utc_now)
    source = Column(String(64), nullable=False, default="manual")
    command_text = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)

    project = relationship("Project")


class ObservationRun(Base):
    __tablename__ = "observation_runs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    root_path = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="running")
    file_count = Column(Integer, nullable=False, default=0)
    component_count = Column(Integer, nullable=False, default=0)
    link_count = Column(Integer, nullable=False, default=0)
    unresolved_link_count = Column(Integer, nullable=False, default=0)
    included_file_count = Column(Integer, nullable=False, default=0)
    excluded_file_count = Column(Integer, nullable=False, default=0)
    max_files_limit = Column(Integer, nullable=False, default=500)
    failure_reason = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=utc_now)
    completed_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="observation_runs")
    observed_files = relationship(
        "ObservedFile",
        back_populates="observation_run",
        cascade="all, delete-orphan",
    )
    observed_components = relationship(
        "ObservedComponent",
        back_populates="observation_run",
        cascade="all, delete-orphan",
    )
    component_links = relationship(
        "ComponentLink",
        back_populates="observation_run",
        cascade="all, delete-orphan",
    )
    observation_maps = relationship(
        "ObservationMap",
        back_populates="observation_run",
        cascade="all, delete-orphan",
    )
    outgoing_diffs = relationship(
        "ObservationDiff",
        back_populates="from_run",
        cascade="all, delete-orphan",
        foreign_keys="ObservationDiff.from_run_id",
    )
    incoming_diffs = relationship(
        "ObservationDiff",
        back_populates="to_run",
        foreign_keys="ObservationDiff.to_run_id",
    )


class ObservedFile(Base):
    __tablename__ = "observed_files"

    id = Column(Integer, primary_key=True, index=True)
    observation_run_id = Column(
        Integer,
        ForeignKey("observation_runs.id"),
        nullable=False,
        index=True,
    )
    path = Column(Text, nullable=False)
    file_kind = Column(String(64), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    line_count = Column(Integer, nullable=True)
    content_text = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    observation_run = relationship("ObservationRun", back_populates="observed_files")
    observed_components = relationship(
        "ObservedComponent",
        back_populates="observed_file",
        cascade="all, delete-orphan",
    )


class ObservedComponent(Base):
    __tablename__ = "observed_components"

    id = Column(Integer, primary_key=True, index=True)
    observation_run_id = Column(
        Integer,
        ForeignKey("observation_runs.id"),
        nullable=False,
        index=True,
    )
    observed_file_id = Column(
        Integer,
        ForeignKey("observed_files.id"),
        nullable=False,
        index=True,
    )
    component_key = Column(String(255), nullable=False, index=True)
    component_kind = Column(String(64), nullable=False)
    display_name = Column(String(255), nullable=False)
    source_path = Column(Text, nullable=False)
    layer = Column(String(64), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    observation_run = relationship("ObservationRun", back_populates="observed_components")
    observed_file = relationship("ObservedFile", back_populates="observed_components")
    links_from = relationship(
        "ComponentLink",
        back_populates="source_component",
        foreign_keys="ComponentLink.source_component_id",
        cascade="all, delete-orphan",
    )
    links_to = relationship(
        "ComponentLink",
        back_populates="target_component",
        foreign_keys="ComponentLink.target_component_id",
    )


class ComponentLink(Base):
    __tablename__ = "component_links"

    id = Column(Integer, primary_key=True, index=True)
    observation_run_id = Column(
        Integer,
        ForeignKey("observation_runs.id"),
        nullable=False,
        index=True,
    )
    source_component_id = Column(
        Integer,
        ForeignKey("observed_components.id"),
        nullable=False,
        index=True,
    )
    target_component_id = Column(
        Integer,
        ForeignKey("observed_components.id"),
        nullable=True,
        index=True,
    )
    relation_type = Column(String(64), nullable=False)
    target_path = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    observation_run = relationship("ObservationRun", back_populates="component_links")
    source_component = relationship(
        "ObservedComponent",
        back_populates="links_from",
        foreign_keys=[source_component_id],
    )
    target_component = relationship(
        "ObservedComponent",
        back_populates="links_to",
        foreign_keys=[target_component_id],
    )


class ObservationMap(Base):
    __tablename__ = "observation_maps"

    id = Column(Integer, primary_key=True, index=True)
    observation_run_id = Column(
        Integer,
        ForeignKey("observation_runs.id"),
        nullable=False,
        index=True,
    )
    map_key = Column(String(128), nullable=False)
    map_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    observation_run = relationship("ObservationRun", back_populates="observation_maps")


class ObservationDiff(Base):
    __tablename__ = "observation_diffs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    from_run_id = Column(Integer, ForeignKey("observation_runs.id"), nullable=False, index=True)
    to_run_id = Column(Integer, ForeignKey("observation_runs.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="completed")
    file_diff_count = Column(Integer, nullable=False, default=0)
    component_diff_count = Column(Integer, nullable=False, default=0)
    link_diff_count = Column(Integer, nullable=False, default=0)
    summary_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="observation_diffs")
    from_run = relationship(
        "ObservationRun",
        back_populates="outgoing_diffs",
        foreign_keys=[from_run_id],
    )
    to_run = relationship(
        "ObservationRun",
        back_populates="incoming_diffs",
        foreign_keys=[to_run_id],
    )
    file_diffs = relationship(
        "FileDiff",
        back_populates="observation_diff",
        cascade="all, delete-orphan",
    )
    component_diffs = relationship(
        "ComponentDiff",
        back_populates="observation_diff",
        cascade="all, delete-orphan",
    )
    link_diffs = relationship(
        "LinkDiff",
        back_populates="observation_diff",
        cascade="all, delete-orphan",
    )
    governor_checks = relationship(
        "GovernorCheck",
        back_populates="observation_diff",
        cascade="all, delete-orphan",
    )


class FileDiff(Base):
    __tablename__ = "file_diffs"

    id = Column(Integer, primary_key=True, index=True)
    observation_diff_id = Column(
        Integer,
        ForeignKey("observation_diffs.id"),
        nullable=False,
        index=True,
    )
    path = Column(Text, nullable=False, index=True)
    diff_type = Column(String(32), nullable=False)
    from_sha256 = Column(String(64), nullable=True)
    to_sha256 = Column(String(64), nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    observation_diff = relationship("ObservationDiff", back_populates="file_diffs")


class ComponentDiff(Base):
    __tablename__ = "component_diffs"

    id = Column(Integer, primary_key=True, index=True)
    observation_diff_id = Column(
        Integer,
        ForeignKey("observation_diffs.id"),
        nullable=False,
        index=True,
    )
    component_key = Column(String(255), nullable=False, index=True)
    diff_type = Column(String(32), nullable=False)
    from_component_kind = Column(String(64), nullable=True)
    to_component_kind = Column(String(64), nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    observation_diff = relationship("ObservationDiff", back_populates="component_diffs")


class LinkDiff(Base):
    __tablename__ = "link_diffs"

    id = Column(Integer, primary_key=True, index=True)
    observation_diff_id = Column(
        Integer,
        ForeignKey("observation_diffs.id"),
        nullable=False,
        index=True,
    )
    link_key = Column(Text, nullable=False, index=True)
    diff_type = Column(String(32), nullable=False)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    observation_diff = relationship("ObservationDiff", back_populates="link_diffs")


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_name = Column(String(255), nullable=False, unique=True)
    rule_kind = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False, default="info")
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=utc_now)

    governor_checks = relationship(
        "GovernorCheck",
        back_populates="policy_rule",
    )


class GovernorCheck(Base):
    __tablename__ = "governor_checks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    observation_diff_id = Column(Integer, ForeignKey("observation_diffs.id"), nullable=False, index=True)
    scope_binding_id = Column(Integer, ForeignKey("scope_bindings.id"), nullable=False, index=True)
    policy_rule_id = Column(Integer, ForeignKey("policy_rules.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="completed")
    decision = Column(String(32), nullable=False)
    rationale = Column(Text, nullable=False)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="governor_checks")
    observation_diff = relationship("ObservationDiff", back_populates="governor_checks")
    scope_binding = relationship("ScopeBinding", back_populates="governor_checks")
    policy_rule = relationship("PolicyRule", back_populates="governor_checks")


class ProjectEvent(Base):
    __tablename__ = "project_events"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    related_object_type = Column(String(64), nullable=True)
    related_object_id = Column(Integer, nullable=True)
    event_summary = Column(Text, nullable=False)
    event_payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="project_events")


class OverviewState(Base):
    __tablename__ = "overview_state"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    state_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="overview_states")


class ArchitectureState(Base):
    __tablename__ = "architecture_state"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    state_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="architecture_states")


class DiffState(Base):
    __tablename__ = "diff_state"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    state_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="diff_states")


class GovernorState(Base):
    __tablename__ = "governor_state"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    state_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False, default=utc_now)

    project = relationship("Project", back_populates="governor_states")
