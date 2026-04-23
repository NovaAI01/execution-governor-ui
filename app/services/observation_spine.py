import ast
import hashlib
import json
import mimetypes
import re
from datetime import UTC, datetime
from pathlib import Path

from app.db import SessionLocal
from app.models import (
    ComponentLink,
    ObservationMap,
    ObservationRun,
    ObservedComponent,
    ObservedFile,
)
from app.services.timeline_core import record_project_event

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "venv",
    "data",
}

IGNORED_FILE_NAMES = {
    ".DS_Store",
}

IGNORED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".sqlite3",
    ".log",
    ".db",
    ".db-journal",
}

TEXT_EXTENSIONS = {
    ".py",
    ".html",
    ".css",
    ".js",
    ".json",
    ".txt",
    ".md",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".sh",
}

HTTP_DECORATORS = {"get", "post", "put", "patch", "delete"}

LAYER_LABELS = {
    "app/main.py": "bootstrap",
    "app/db.py": "models_db",
    "app/models.py": "models_db",
}


def _utc_now():
    return datetime.now(UTC)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    guessed, _ = mimetypes.guess_type(path.name)
    return bool(guessed and guessed.startswith("text"))


def _safe_read_text(path: Path, max_chars: int = 50000) -> str | None:
    if not _is_text_file(path):
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    return text[:max_chars]


def _should_ignore_file(rel: Path) -> tuple[bool, str | None]:
    if any(part in IGNORED_DIRS for part in rel.parts):
        return True, "ignored_dir"
    if rel.name in IGNORED_FILE_NAMES:
        return True, "ignored_name"
    if any(str(rel).endswith(suffix) for suffix in IGNORED_SUFFIXES):
        return True, "ignored_suffix"
    return False, None


def _iter_project_files(root: Path, max_files: int):
    included = []
    excluded = []

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)

        if not path.is_file():
            continue

        if any(part in IGNORED_DIRS for part in rel.parts):
            continue

        ignored, reason = _should_ignore_file(rel)
        if ignored:
            excluded.append({"path": str(rel), "reason": reason})
            continue

        included.append({"path": path, "rel_path": str(rel)})
        if len(included) >= max_files:
            break

    return included, excluded

def _layer_for_path(rel_path: str) -> str:
    if rel_path in LAYER_LABELS:
        return LAYER_LABELS[rel_path]
    if rel_path.startswith("app/routes/"):
        return "routes"
    if rel_path.startswith("app/services/"):
        return "services"
    if rel_path.startswith("app/templates/"):
        return "templates"
    return "other"


def _component_kind_for_path(rel_path: str) -> str:
    if rel_path.endswith(".py"):
        return "python_module"
    if rel_path.endswith(".html"):
        return "template"
    return "file"


def _display_name_for_path(rel_path: str) -> str:
    return Path(rel_path).name


def _resolve_app_module_target(root: Path, module_name: str) -> str | None:
    if not module_name.startswith("app."):
        return None

    rel = module_name.replace(".", "/")
    py_candidate = root / f"{rel}.py"
    if py_candidate.exists():
        return str(py_candidate.relative_to(root))

    init_candidate = root / rel / "__init__.py"
    if init_candidate.exists():
        return str(init_candidate.relative_to(root))

    return None


def _resolve_template_target(root: Path, template_name: str) -> str | None:
    candidate = root / "app" / "templates" / template_name
    if candidate.exists():
        return str(candidate.relative_to(root))
    return None


def _parse_python_content(root: Path, text: str) -> dict:
    result = {
        "imports": [],
        "renders": [],
        "http_routes": [],
        "classes": [],
        "functions": [],
    }

    try:
        tree = ast.parse(text)
    except SyntaxError:
        result["parse_error"] = "syntax_error"
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target_path = _resolve_app_module_target(root, alias.name)
                if target_path:
                    result["imports"].append(
                        {
                            "relation_type": "imports",
                            "target_path": target_path,
                            "label": alias.name,
                        }
                    )

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            target_path = _resolve_app_module_target(root, module)
            if target_path:
                result["imports"].append(
                    {
                        "relation_type": "imports",
                        "target_path": target_path,
                        "label": module,
                    }
                )

        elif isinstance(node, ast.ClassDef):
            result["classes"].append(node.name)

        elif isinstance(node, ast.FunctionDef):
            result["functions"].append(node.name)
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    if decorator.func.attr in HTTP_DECORATORS:
                        route_path = None
                        if decorator.args and isinstance(decorator.args[0], ast.Constant):
                            route_path = str(decorator.args[0].value)
                        result["http_routes"].append(
                            {
                                "name": node.name,
                                "method": decorator.func.attr.upper(),
                                "path": route_path,
                            }
                        )

        elif isinstance(node, ast.Call):
            func = node.func
            template_name = None

            if isinstance(func, ast.Attribute) and func.attr == "TemplateResponse":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    template_name = str(node.args[1].value)

            if template_name:
                target_path = _resolve_template_target(root, template_name)
                if target_path:
                    result["renders"].append(
                        {
                            "relation_type": "renders",
                            "target_path": target_path,
                            "label": template_name,
                        }
                    )

    return result


def _parse_template_content(root: Path, text: str) -> dict:
    includes = []
    extends_match = re.search(r'\{%\s*extends\s+"([^"]+)"\s*%\}', text)
    extends_target = None

    if extends_match:
        extends_name = extends_match.group(1)
        extends_target = _resolve_template_target(root, extends_name)

    for match in re.findall(r'\{%\s*include\s+"([^"]+)"\s*%\}', text):
        target_path = _resolve_template_target(root, match)
        if target_path:
            includes.append(
                {
                    "relation_type": "includes",
                    "target_path": target_path,
                    "label": match,
                }
            )

    return {
        "extends": extends_target,
        "includes": includes,
    }


def _build_policy_map(max_files: int) -> dict:
    return {
        "max_files": max_files,
        "ignored_dirs": sorted(IGNORED_DIRS),
        "ignored_file_names": sorted(IGNORED_FILE_NAMES),
        "ignored_suffixes": sorted(IGNORED_SUFFIXES),
        "text_extensions": sorted(TEXT_EXTENSIONS),
    }


def capture_observation_run(project_id: int, root_path: str, max_files: int = 500) -> dict:
    root = Path(root_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("Project root does not exist.")

    db = SessionLocal()
    run = ObservationRun(
        project_id=project_id,
        root_path=str(root),
        status="running",
        max_files_limit=max_files,
        started_at=_utc_now(),
    )

    try:
        db.add(run)
        db.flush()

        included_files, excluded_files = _iter_project_files(root, max_files=max_files)

        file_count = 0
        component_count = 0
        link_count = 0
        unresolved_link_count = 0

        components_by_path = {}
        pending_links = []

        kind_counts = {}
        layer_counts = {}

        for item in included_files:
            path = item["path"]
            rel_path = item["rel_path"]

            raw = path.read_bytes()
            content_text = _safe_read_text(path)
            line_count = content_text.count("\n") + 1 if content_text else None
            file_kind = path.suffix.lower().lstrip(".") or "no_extension"

            observed_file = ObservedFile(
                observation_run_id=run.id,
                path=rel_path,
                file_kind=file_kind,
                sha256=_sha256_bytes(raw),
                size_bytes=len(raw),
                line_count=line_count,
                content_text=content_text,
            )
            db.add(observed_file)
            db.flush()
            file_count += 1

            component_kind = _component_kind_for_path(rel_path)
            layer = _layer_for_path(rel_path)
            metadata = {
                "file_kind": file_kind,
                "size_bytes": len(raw),
                "line_count": line_count,
            }

            if content_text and rel_path.endswith(".py"):
                parsed = _parse_python_content(root, content_text)
                metadata.update(
                    {
                        "class_count": len(parsed.get("classes", [])),
                        "function_count": len(parsed.get("functions", [])),
                        "http_route_count": len(parsed.get("http_routes", [])),
                        "render_count": len(parsed.get("renders", [])),
                        "import_count": len(parsed.get("imports", [])),
                        "http_routes": parsed.get("http_routes", []),
                        "classes": parsed.get("classes", []),
                        "functions": parsed.get("functions", []),
                    }
                )
                if parsed.get("parse_error"):
                    metadata["parse_error"] = parsed["parse_error"]

                pending_links.extend(
                    [
                        (rel_path, item["target_path"], item["relation_type"], item["label"])
                        for item in parsed["imports"]
                    ]
                )
                pending_links.extend(
                    [
                        (rel_path, item["target_path"], item["relation_type"], item["label"])
                        for item in parsed["renders"]
                    ]
                )

            elif content_text and rel_path.endswith(".html"):
                parsed = _parse_template_content(root, content_text)
                metadata.update(
                    {
                        "include_count": len(parsed.get("includes", [])),
                        "extends": parsed.get("extends"),
                    }
                )

                if parsed.get("extends"):
                    pending_links.append(
                        (rel_path, parsed["extends"], "extends", "template_extends")
                    )

                pending_links.extend(
                    [
                        (rel_path, item["target_path"], item["relation_type"], item["label"])
                        for item in parsed["includes"]
                    ]
                )

            observed_component = ObservedComponent(
                observation_run_id=run.id,
                observed_file_id=observed_file.id,
                component_key=f"{component_kind}:{rel_path}",
                component_kind=component_kind,
                display_name=_display_name_for_path(rel_path),
                source_path=rel_path,
                layer=layer,
                metadata_json=json.dumps(metadata, sort_keys=True),
            )
            db.add(observed_component)
            db.flush()

            components_by_path[rel_path] = observed_component
            component_count += 1
            kind_counts[component_kind] = kind_counts.get(component_kind, 0) + 1
            layer_counts[layer] = layer_counts.get(layer, 0) + 1

        unresolved_links = []

        for source_path, target_path, relation_type, label in pending_links:
            source_component = components_by_path.get(source_path)
            target_component = components_by_path.get(target_path)

            if not source_component:
                continue

            link = ComponentLink(
                observation_run_id=run.id,
                source_component_id=source_component.id,
                target_component_id=target_component.id if target_component else None,
                relation_type=relation_type,
                target_path=target_path,
                metadata_json=json.dumps(
                    {
                        "label": label,
                        "is_resolved": bool(target_component),
                    },
                    sort_keys=True,
                ),
            )
            db.add(link)
            link_count += 1

            if not target_component:
                unresolved_link_count += 1
                unresolved_links.append(
                    {
                        "source_path": source_path,
                        "relation_type": relation_type,
                        "target_path": target_path,
                        "label": label,
                    }
                )

        run.status = "completed"
        run.file_count = file_count
        run.component_count = component_count
        run.link_count = link_count
        run.unresolved_link_count = unresolved_link_count
        run.included_file_count = len(included_files)
        run.excluded_file_count = len(excluded_files)
        run.completed_at = _utc_now()

        digest_map = {
            "run_id": run.id,
            "root_path": str(root),
            "counts": {
                "files": file_count,
                "components": component_count,
                "links": link_count,
                "unresolved_links": unresolved_link_count,
                "included_files": len(included_files),
                "excluded_files": len(excluded_files),
            },
            "component_kinds": kind_counts,
            "layers": layer_counts,
        }

        db.add(
            ObservationMap(
                observation_run_id=run.id,
                map_key="architecture_digest",
                map_json=json.dumps(digest_map, indent=2, sort_keys=True),
            )
        )

        db.add(
            ObservationMap(
                observation_run_id=run.id,
                map_key="component_catalog",
                map_json=json.dumps(
                    sorted(components_by_path.keys()),
                    indent=2,
                ),
            )
        )

        db.add(
            ObservationMap(
                observation_run_id=run.id,
                map_key="observation_policy",
                map_json=json.dumps(_build_policy_map(max_files), indent=2, sort_keys=True),
            )
        )

        db.add(
            ObservationMap(
                observation_run_id=run.id,
                map_key="unresolved_links",
                map_json=json.dumps(unresolved_links, indent=2, sort_keys=True),
            )
        )

        db.commit()

        record_project_event(
            project_id=project_id,
            event_type="observation.completed",
            related_object_type="observation_run",
            related_object_id=run.id,
            event_summary=f"Observation run {run.id} completed.",
            event_payload={
                "run_id": run.id,
                "status": run.status,
                "file_count": file_count,
                "component_count": component_count,
                "link_count": link_count,
                "unresolved_link_count": unresolved_link_count,
            },
        )

        return {
            "run_id": run.id,
            "status": run.status,
            "file_count": file_count,
            "component_count": component_count,
            "link_count": link_count,
            "unresolved_link_count": unresolved_link_count,
            "included_file_count": len(included_files),
            "excluded_file_count": len(excluded_files),
        }

    except Exception as exc:
        db.rollback()

        recovery = SessionLocal()
        try:
            failed_run = recovery.query(ObservationRun).filter(ObservationRun.id == run.id).first()
            if failed_run:
                failed_run.status = "failed"
                failed_run.failure_reason = str(exc)
                failed_run.completed_at = _utc_now()
                recovery.commit()

                record_project_event(
                    project_id=project_id,
                    event_type="observation.failed",
                    related_object_type="observation_run",
                    related_object_id=failed_run.id,
                    event_summary=f"Observation run {failed_run.id} failed.",
                    event_payload={
                        "run_id": failed_run.id,
                        "status": failed_run.status,
                        "failure_reason": failed_run.failure_reason,
                    },
                )
        finally:
            recovery.close()

        raise
    finally:
        db.close()
