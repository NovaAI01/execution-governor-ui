import ast
import re
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "venv",
    "data",
}

PY_EXTENSIONS = {".py"}
TPL_EXTENSIONS = {".html"}

LAYER_ORDER = ["bootstrap", "routes", "services", "models_db", "templates", "other"]
LAYER_LABELS = {
    "bootstrap": "App Bootstrap",
    "routes": "Routes",
    "services": "Services",
    "models_db": "Models / DB",
    "templates": "Templates",
    "other": "Other",
}


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        yield path, str(rel)


def _classify_layer(rel_path: str) -> str:
    if rel_path == "app/main.py":
        return "bootstrap"
    if rel_path.startswith("app/routes/"):
        return "routes"
    if rel_path.startswith("app/services/"):
        return "services"
    if rel_path in {"app/models.py", "app/db.py"}:
        return "models_db"
    if rel_path.startswith("app/templates/"):
        return "templates"
    return "other"


def _role_for_node(rel_path: str, kind: str) -> str:
    if rel_path == "app/main.py":
        return "Application bootstrap"
    if rel_path.startswith("app/routes/"):
        return "Route module"
    if rel_path.startswith("app/services/"):
        return "Service module"
    if rel_path == "app/models.py":
        return "ORM models"
    if rel_path == "app/db.py":
        return "Database bootstrap"
    if rel_path == "app/templates/overview.html":
        return "Overview page"
    if rel_path.startswith("app/templates/partials/"):
        return "Template partial"
    if rel_path.startswith("app/templates/"):
        return "Template page"
    return "Python module" if kind == "python" else "Template"


def _friendly_label(target: str) -> str:
    if target.startswith("app."):
        return target.split(".")[-1]
    if target.startswith("partials/"):
        return target.split("/")[-1]
    if "/" in target:
        return target.split("/")[-1]
    return target


def _resolve_import_target(root: Path, module_name: str):
    if not module_name.startswith("app."):
        return None

    rel = module_name.replace(".", "/")
    candidate = root / f"{rel}.py"
    if candidate.exists():
        return str(candidate.relative_to(root))

    init_candidate = root / rel / "__init__.py"
    if init_candidate.exists():
        return str(init_candidate.relative_to(root))

    return None


def _resolve_template_target(root: Path, template_name: str):
    candidate = root / "app" / "templates" / template_name
    if candidate.exists():
        return str(candidate.relative_to(root))
    return None


def _parse_python(root: Path, path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    primary_links = []
    external_imports = []

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return primary_links, external_imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name
                target_path = _resolve_import_target(root, target)
                if target_path:
                    primary_links.append(
                        {"rel": "imports", "target": target, "target_path": target_path}
                    )
                else:
                    external_imports.append(target)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            target_path = _resolve_import_target(root, module)
            if target_path:
                primary_links.append(
                    {"rel": "imports", "target": module, "target_path": target_path}
                )
            elif module:
                external_imports.append(module)

        elif isinstance(node, ast.Call):
            func = node.func
            template_name = None

            if isinstance(func, ast.Attribute) and func.attr == "TemplateResponse":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    template_name = str(node.args[1].value)
            elif isinstance(func, ast.Name) and func.id == "TemplateResponse":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    template_name = str(node.args[1].value)

            if template_name:
                target_path = _resolve_template_target(root, template_name)
                primary_links.append(
                    {"rel": "renders", "target": template_name, "target_path": target_path}
                )

    return primary_links, sorted(set(external_imports))


def _parse_template(root: Path, path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    primary_links = []

    for match in re.findall(r'\{%\s*include\s+"([^"]+)"\s*%\}', text):
        primary_links.append(
            {
                "rel": "includes",
                "target": match,
                "target_path": _resolve_template_target(root, match),
            }
        )

    for match in re.findall(r'action="([^"]+)"', text):
        primary_links.append({"rel": "posts_to", "target": match, "target_path": None})

    for match in re.findall(r'fetch\(\s*[\'"]([^\'"]+)[\'"]', text):
        primary_links.append({"rel": "fetches", "target": match, "target_path": None})

    return primary_links, []


def build_code_graph(root_path: str, scope: str = "all", focus: str | None = None, max_files: int = 300):
    if not root_path:
        return {"ok": False, "error": "No root path set.", "sections": [], "total_nodes": 0}

    root = Path(root_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {"ok": False, "error": "Root path does not exist.", "sections": [], "total_nodes": 0}

    nodes_by_path = {}
    grouped = {layer: [] for layer in LAYER_ORDER}
    count = 0

    for path, rel in _iter_files(root):
        if count >= max_files:
            break

        ext = path.suffix.lower()
        if ext not in PY_EXTENSIONS and ext not in TPL_EXTENSIONS:
            continue

        kind = "python" if ext in PY_EXTENSIONS else "template"
        layer = _classify_layer(rel)

        if scope == "python" and kind != "python":
            continue
        if scope == "templates" and kind != "template":
            continue
        if scope == "routes" and layer != "routes":
            continue

        primary_links, external_imports = (
            _parse_python(root, path) if kind == "python" else _parse_template(root, path)
        )

        if not primary_links and not external_imports:
            continue

        node = {
            "path": rel,
            "kind": kind,
            "layer": layer,
            "layer_label": LAYER_LABELS[layer],
            "role": _role_for_node(rel, kind),
            "primary_links": primary_links,
            "external_imports": external_imports,
            "reverse_links": [],
        }
        nodes_by_path[rel] = node
        grouped[layer].append(node)
        count += 1

    for node in nodes_by_path.values():
        for link in node["primary_links"]:
            target_path = link.get("target_path")
            if target_path and target_path in nodes_by_path:
                nodes_by_path[target_path]["reverse_links"].append(
                    {
                        "rel": link["rel"],
                        "source_path": node["path"],
                        "source_role": node["role"],
                        "label": _friendly_label(node["path"]),
                    }
                )

    sections = []
    total_nodes = 0
    for layer in LAYER_ORDER:
        nodes = grouped[layer]
        if not nodes:
            continue

        nav_nodes = [
            {"path": node["path"], "label": _friendly_label(node["path"]), "role": node["role"]}
            for node in nodes
        ]
        sections.append(
            {
                "key": layer,
                "label": LAYER_LABELS[layer],
                "count": len(nodes),
                "nav_nodes": nav_nodes,
            }
        )
        total_nodes += len(nodes)

    focus_path = focus if focus in nodes_by_path else None
    if not focus_path and sections:
        focus_path = sections[0]["nav_nodes"][0]["path"]

    focused_node = nodes_by_path.get(focus_path) if focus_path else None

    return {
        "ok": True,
        "error": None,
        "sections": sections,
        "scope": scope,
        "total_nodes": total_nodes,
        "focus_path": focus_path,
        "focused_node": focused_node,
    }
