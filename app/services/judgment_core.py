import json

from app.db import SessionLocal
from app.models import GovernorCheck, ObservationDiff, PolicyRule, Project, ScopeBinding


DEFAULT_SCOPE_BINDING_NAME = "default_project_scope"
DEFAULT_POLICY_RULES = [
    {
        "rule_name": "no_removed_files",
        "rule_kind": "file_diff",
        "severity": "warn",
        "config_json": {"blocked_diff_types": ["removed"]},
    },
    {
        "rule_name": "no_removed_components",
        "rule_kind": "component_diff",
        "severity": "warn",
        "config_json": {"blocked_diff_types": ["removed"]},
    },
    {
        "rule_name": "no_removed_links",
        "rule_kind": "link_diff",
        "severity": "info",
        "config_json": {"blocked_diff_types": ["removed"]},
    },
]


def _parse_json(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def ensure_default_scope_binding(project_id: int) -> int:
    db = SessionLocal()
    try:
        binding = (
            db.query(ScopeBinding)
            .filter(
                ScopeBinding.project_id == project_id,
                ScopeBinding.binding_name == DEFAULT_SCOPE_BINDING_NAME,
            )
            .first()
        )
        if binding:
            return binding.id

        project = db.query(Project).filter(Project.id == project_id).first()
        root_path = project.root_path if project and project.root_path else ""
        included = [root_path] if root_path else []

        binding = ScopeBinding(
            project_id=project_id,
            binding_name=DEFAULT_SCOPE_BINDING_NAME,
            included_paths_json=json.dumps(included),
            excluded_paths_json=json.dumps([]),
            notes="Default scaffold scope binding for project-level judgment.",
        )
        db.add(binding)
        db.commit()
        db.refresh(binding)
        return binding.id
    finally:
        db.close()


def ensure_default_policy_rules() -> list[int]:
    db = SessionLocal()
    try:
        ids = []
        for rule in DEFAULT_POLICY_RULES:
            existing = (
                db.query(PolicyRule)
                .filter(PolicyRule.rule_name == rule["rule_name"])
                .first()
            )
            if existing:
                ids.append(existing.id)
                continue

            created = PolicyRule(
                rule_name=rule["rule_name"],
                rule_kind=rule["rule_kind"],
                severity=rule["severity"],
                config_json=json.dumps(rule["config_json"], sort_keys=True),
            )
            db.add(created)
            db.flush()
            ids.append(created.id)

        db.commit()
        return ids
    finally:
        db.close()


def run_judgment_for_latest_diff(project_id: int) -> dict:
    scope_binding_id = ensure_default_scope_binding(project_id)
    ensure_default_policy_rules()

    db = SessionLocal()
    try:
        latest_diff = (
            db.query(ObservationDiff)
            .filter(ObservationDiff.project_id == project_id)
            .order_by(ObservationDiff.id.desc())
            .first()
        )
        if not latest_diff:
            raise ValueError("No observation diff exists for this project.")

        existing_checks = (
            db.query(GovernorCheck)
            .filter(GovernorCheck.observation_diff_id == latest_diff.id)
            .count()
        )
        if existing_checks > 0:
            return {
                "observation_diff_id": latest_diff.id,
                "created_checks": 0,
                "message": "Judgment already exists for latest diff.",
            }

        policy_rules = db.query(PolicyRule).order_by(PolicyRule.id.asc()).all()

        created_checks = 0

        for rule in policy_rules:
            config = _parse_json(rule.config_json, {})
            blocked = set(config.get("blocked_diff_types", []))

            if rule.rule_name == "no_removed_files":
                has_violation = any(
                    row.diff_type in blocked for row in latest_diff.file_diffs
                )
                details = {
                    "blocked_diff_types": sorted(blocked),
                    "observed_file_diff_types": sorted(
                        {row.diff_type for row in latest_diff.file_diffs}
                    ),
                }
            elif rule.rule_name == "no_removed_components":
                has_violation = any(
                    row.diff_type in blocked for row in latest_diff.component_diffs
                )
                details = {
                    "blocked_diff_types": sorted(blocked),
                    "observed_component_diff_types": sorted(
                        {row.diff_type for row in latest_diff.component_diffs}
                    ),
                }
            elif rule.rule_name == "no_removed_links":
                has_violation = any(
                    row.diff_type in blocked for row in latest_diff.link_diffs
                )
                details = {
                    "blocked_diff_types": sorted(blocked),
                    "observed_link_diff_types": sorted(
                        {row.diff_type for row in latest_diff.link_diffs}
                    ),
                }
            else:
                has_violation = False
                details = {"note": "Unknown scaffold rule kind."}

            decision = "review_required" if has_violation else "pass"
            rationale = (
                f"Rule {rule.rule_name} triggered review."
                if has_violation
                else f"Rule {rule.rule_name} passed."
            )

            check = GovernorCheck(
                project_id=project_id,
                observation_diff_id=latest_diff.id,
                scope_binding_id=scope_binding_id,
                policy_rule_id=rule.id,
                status="completed",
                decision=decision,
                rationale=rationale,
                details_json=json.dumps(details, sort_keys=True),
            )
            db.add(check)
            created_checks += 1

        db.commit()

        return {
            "observation_diff_id": latest_diff.id,
            "created_checks": created_checks,
            "message": "Judgment checks created.",
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
