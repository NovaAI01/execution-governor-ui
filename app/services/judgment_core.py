import json

from app.db import SessionLocal
from app.models import (
    ComponentDiff,
    FileDiff,
    GovernorCheck,
    LinkDiff,
    ObservationDiff,
    PolicyRule,
    ScopeBinding,
)
from app.services.timeline_core import record_project_event


def _parse_json(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def ensure_default_scope_binding(project_id: int, root_path: str | None) -> ScopeBinding:
    db = SessionLocal()
    try:
        binding = (
            db.query(ScopeBinding)
            .filter(ScopeBinding.project_id == project_id)
            .order_by(ScopeBinding.id.asc())
            .first()
        )
        if binding:
            return binding

        included_paths = [root_path] if root_path else []
        binding = ScopeBinding(
            project_id=project_id,
            binding_name="default_project_scope",
            included_paths_json=json.dumps(included_paths),
            excluded_paths_json=json.dumps([]),
            notes="Default scaffold scope binding for project-level judgment.",
        )
        db.add(binding)
        db.commit()
        db.refresh(binding)
        return binding
    finally:
        db.close()


def ensure_default_policy_rules() -> list[PolicyRule]:
    db = SessionLocal()
    try:
        existing = db.query(PolicyRule).order_by(PolicyRule.id.asc()).all()
        if existing:
            return existing

        rows = [
            PolicyRule(
                rule_name="no_removed_files",
                rule_kind="file_diff",
                severity="warn",
                config_json=json.dumps({"blocked_diff_types": ["removed"]}, sort_keys=True),
            ),
            PolicyRule(
                rule_name="no_removed_components",
                rule_kind="component_diff",
                severity="warn",
                config_json=json.dumps({"blocked_diff_types": ["removed"]}, sort_keys=True),
            ),
            PolicyRule(
                rule_name="no_removed_links",
                rule_kind="link_diff",
                severity="info",
                config_json=json.dumps({"blocked_diff_types": ["removed"]}, sort_keys=True),
            ),
        ]
        db.add_all(rows)
        db.commit()
        return db.query(PolicyRule).order_by(PolicyRule.id.asc()).all()
    finally:
        db.close()


def _normalize_scope_paths(paths: list[str]) -> list[str]:
    normalized = []
    for value in paths:
        text = str(value).strip()
        if not text:
            continue
        normalized.append(text.rstrip("/"))
    return normalized


def _path_matches(path: str, prefixes: list[str]) -> bool:
    for prefix in prefixes:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def _to_repo_relative(path: str, repo_roots: list[str]) -> str:
    clean = str(path).strip().rstrip("/")
    for root in repo_roots:
        if clean == root:
            return ""
        if clean.startswith(root + "/"):
            return clean[len(root) + 1 :]
    return clean


def _classify_paths(paths: list[str], included_paths: list[str], excluded_paths: list[str], repo_roots: list[str]) -> dict:
    repo_relative_paths = []
    for path in paths:
        text = str(path).strip()
        if not text:
            continue
        repo_relative_paths.append(_to_repo_relative(text, repo_roots))

    unique_paths = sorted({path for path in repo_relative_paths if path})
    if not unique_paths:
        return {
            "scope_result": "OUT_OF_SCOPE",
            "in_scope_paths": [],
            "out_of_scope_paths": [],
            "considered_paths": [],
        }

    included = _normalize_scope_paths(included_paths)
    excluded = _normalize_scope_paths(excluded_paths)

    in_scope_paths = []
    out_of_scope_paths = []

    for path in unique_paths:
        included_ok = True if not included else _path_matches(path, included)
        excluded_hit = _path_matches(path, excluded)

        if included_ok and not excluded_hit:
            in_scope_paths.append(path)
        else:
            out_of_scope_paths.append(path)

    if in_scope_paths and out_of_scope_paths:
        scope_result = "PARTIAL_SCOPE"
    elif in_scope_paths:
        scope_result = "IN_SCOPE"
    else:
        scope_result = "OUT_OF_SCOPE"

    return {
        "scope_result": scope_result,
        "in_scope_paths": in_scope_paths,
        "out_of_scope_paths": out_of_scope_paths,
        "considered_paths": unique_paths,
    }


def _classify_file_diff(row, included_paths: list[str], excluded_paths: list[str], repo_roots: list[str]) -> dict:
    return _classify_paths([row.path], included_paths, excluded_paths, repo_roots)


def _classify_component_diff(row, included_paths: list[str], excluded_paths: list[str], repo_roots: list[str]) -> dict:
    details = _parse_json(row.details_json, {})
    paths = []

    if isinstance(details, dict):
        if isinstance(details.get("source_path"), str):
            paths.append(details["source_path"])

        if isinstance(details.get("component_key"), str):
            paths.append(details["component_key"])

        from_part = details.get("from")
        to_part = details.get("to")

        if isinstance(from_part, dict) and isinstance(from_part.get("source_path"), str):
            paths.append(from_part["source_path"])
        if isinstance(to_part, dict) and isinstance(to_part.get("source_path"), str):
            paths.append(to_part["source_path"])

    if not paths and getattr(row, "component_key", None):
        paths.append(str(row.component_key))

    cleaned = []
    for value in paths:
        text = str(value)
        if text.startswith("python_module:"):
            text = text.split(":", 1)[1]
        elif text.startswith("template:"):
            text = text.split(":", 1)[1]
        elif text.startswith("file:"):
            text = text.split(":", 1)[1]
        cleaned.append(text)

    return _classify_paths(cleaned, included_paths, excluded_paths, repo_roots)


def _classify_link_diff(row, included_paths: list[str], excluded_paths: list[str], repo_roots: list[str]) -> dict:
    details = _parse_json(row.details_json, {})
    paths = []

    if isinstance(details, dict):
        if isinstance(details.get("source_path"), str):
            paths.append(details["source_path"])
        if isinstance(details.get("target_path"), str):
            paths.append(details["target_path"])

    if not paths and getattr(row, "link_key", None):
        parts = str(row.link_key).split("|")
        if len(parts) == 3:
            paths.append(parts[0])
            paths.append(parts[2])

    return _classify_paths(paths, included_paths, excluded_paths, repo_roots)


def _build_file_item(row, scope_info: dict) -> dict:
    return {
        "item_type": "file_diff",
        "path": row.path,
        "diff_type": row.diff_type,
        "scope_result": scope_info["scope_result"],
        "in_scope_paths": scope_info["in_scope_paths"],
        "out_of_scope_paths": scope_info["out_of_scope_paths"],
        "considered_paths": scope_info["considered_paths"],
    }


def _build_component_item(row, scope_info: dict) -> dict:
    return {
        "item_type": "component_diff",
        "component_key": row.component_key,
        "diff_type": row.diff_type,
        "scope_result": scope_info["scope_result"],
        "in_scope_paths": scope_info["in_scope_paths"],
        "out_of_scope_paths": scope_info["out_of_scope_paths"],
        "considered_paths": scope_info["considered_paths"],
    }


def _build_link_item(row, scope_info: dict) -> dict:
    return {
        "item_type": "link_diff",
        "link_key": row.link_key,
        "diff_type": row.diff_type,
        "scope_result": scope_info["scope_result"],
        "in_scope_paths": scope_info["in_scope_paths"],
        "out_of_scope_paths": scope_info["out_of_scope_paths"],
        "considered_paths": scope_info["considered_paths"],
    }


def run_judgment_for_latest_diff(project_id: int) -> dict:
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

        root_path = None
        if latest_diff.to_run and latest_diff.to_run.root_path:
            root_path = latest_diff.to_run.root_path
        elif latest_diff.from_run and latest_diff.from_run.root_path:
            root_path = latest_diff.from_run.root_path
    finally:
        db.close()

    scope_binding = ensure_default_scope_binding(project_id, root_path)
    policy_rules = ensure_default_policy_rules()

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

        db.query(GovernorCheck).filter(
            GovernorCheck.observation_diff_id == latest_diff.id
        ).delete()

        included_paths = _parse_json(scope_binding.included_paths_json, [])
        excluded_paths = _parse_json(scope_binding.excluded_paths_json, [])
        repo_roots = [path.rstrip("/") for path in included_paths if str(path).strip().startswith("/")]

        file_diffs = (
            db.query(FileDiff)
            .filter(FileDiff.observation_diff_id == latest_diff.id)
            .order_by(FileDiff.id.asc())
            .all()
        )
        component_diffs = (
            db.query(ComponentDiff)
            .filter(ComponentDiff.observation_diff_id == latest_diff.id)
            .order_by(ComponentDiff.id.asc())
            .all()
        )
        link_diffs = (
            db.query(LinkDiff)
            .filter(LinkDiff.observation_diff_id == latest_diff.id)
            .order_by(LinkDiff.id.asc())
            .all()
        )

        created_checks = 0

        for rule in policy_rules:
            config = _parse_json(rule.config_json, {})
            blocked_types = config.get("blocked_diff_types", ["removed"])

            classified_items = []
            scoped_items = []

            if rule.rule_kind == "file_diff":
                for row in file_diffs:
                    scope_info = _classify_file_diff(row, included_paths, excluded_paths, repo_roots)
                    item = _build_file_item(row, scope_info)
                    classified_items.append(item)
                    if scope_info["scope_result"] != "OUT_OF_SCOPE":
                        scoped_items.append(item)

            elif rule.rule_kind == "component_diff":
                for row in component_diffs:
                    scope_info = _classify_component_diff(row, included_paths, excluded_paths, repo_roots)
                    item = _build_component_item(row, scope_info)
                    classified_items.append(item)
                    if scope_info["scope_result"] != "OUT_OF_SCOPE":
                        scoped_items.append(item)

            elif rule.rule_kind == "link_diff":
                for row in link_diffs:
                    scope_info = _classify_link_diff(row, included_paths, excluded_paths, repo_roots)
                    item = _build_link_item(row, scope_info)
                    classified_items.append(item)
                    if scope_info["scope_result"] != "OUT_OF_SCOPE":
                        scoped_items.append(item)
            else:
                continue

            considered = [item["diff_type"] for item in scoped_items]
            violations = [
                item for item in scoped_items
                if item["diff_type"] in blocked_types
            ]

            if violations:
                decision = "fail"
                rationale = (
                    f"Rule {rule.rule_name} failed. "
                    f"{len(violations)} in-scope or partially in-scope diff(s) matched blocked types."
                )
            else:
                decision = "pass"
                rationale = (
                    f"Rule {rule.rule_name} passed. "
                    f"No in-scope or partially in-scope diffs matched blocked types."
                )

            check = GovernorCheck(
                project_id=project_id,
                observation_diff_id=latest_diff.id,
                policy_rule_id=rule.id,
                scope_binding_id=scope_binding.id,
                status="completed",
                decision=decision,
                rationale=rationale,
                details_json=json.dumps(
                    {
                        "blocked_diff_types": blocked_types,
                        "included_paths": included_paths,
                        "excluded_paths": excluded_paths,
                        "classified_items": classified_items,
                        "considered_diff_types": considered,
                        "violations": violations,
                    },
                    sort_keys=True,
                ),
            )
            db.add(check)
            created_checks += 1

        db.commit()

        record_project_event(
            project_id=project_id,
            event_type="judgment.created",
            related_object_type="observation_diff",
            related_object_id=latest_diff.id,
            event_summary=f"Judgment created for observation diff {latest_diff.id}.",
            event_payload={
                "observation_diff_id": latest_diff.id,
                "created_checks": created_checks,
                "scope_binding_id": scope_binding.id,
                "included_paths": included_paths,
                "excluded_paths": excluded_paths,
            },
        )

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
