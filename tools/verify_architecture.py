# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""AST and token architecture boundary verifier for GOE."""

from __future__ import annotations

import ast
import io
import sys
import tokenize
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from goe.typing import FrozenBaseStruct

__all__ = (
    "ArchitectureViolation",
    "BaselineConfig",
    "load_baseline",
    "main",
    "scan_paths",
)

RULE_NAMES: tuple[str, ...] = (
    "raw-json",
    "sqlglot-boundary",
    "oracledb-boundary",
    "nested-import",
    "member-ordering",
    "inline-comment",
)


class ArchitectureViolation(FrozenBaseStruct, frozen=True):
    """Single architectural boundary or style violation discovered in a source file."""

    path: str
    line: int
    rule: str
    message: str


class BaselineConfig(FrozenBaseStruct, frozen=True):
    """Mapping of rule names to relative file paths suppressed during incremental migration."""

    entries: Mapping[str, frozenset[str]] = {}

    def is_suppressed(self, rule: str, rel_path: str) -> bool:
        """Return True if rel_path is baselined for rule."""
        return rel_path in self.entries.get(rule, frozenset())


def load_baseline(baseline_path: Path) -> BaselineConfig:
    """Load BaselineConfig from a TOML file."""
    if not baseline_path.is_file():
        return BaselineConfig(entries={})
    raw = tomllib.loads(baseline_path.read_text(encoding="utf-8"))
    parsed: dict[str, frozenset[str]] = {}
    for rule in RULE_NAMES:
        section = raw.get(rule, {})
        files = section.get("files", []) if isinstance(section, dict) else []
        parsed[rule] = frozenset(str(item) for item in files)
    return BaselineConfig(entries=parsed)


def scan_paths(
    paths: Sequence[Path],
    *,
    repo_root: Path,
    baseline: BaselineConfig | None = None,
) -> list[ArchitectureViolation]:
    """Scan Python files or directories for architectural violations against optional baseline."""
    py_files = _collect_python_files(paths)
    active_baseline = baseline or BaselineConfig(entries={})
    reported: list[ArchitectureViolation] = []
    observed_by_rule: dict[str, set[str]] = {rule: set() for rule in RULE_NAMES}
    scanned_rel_paths: set[str] = set()

    for file_path in py_files:
        rel_path = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
        scanned_rel_paths.add(rel_path)
        file_violations = _scan_single_file(file_path, rel_path=rel_path)
        for violation in file_violations:
            observed_by_rule.setdefault(violation.rule, set()).add(rel_path)
            if not active_baseline.is_suppressed(violation.rule, rel_path):
                reported.append(violation)

    for rule, suppressed_files in active_baseline.entries.items():
        observed_files = observed_by_rule.get(rule, set())
        for rel_path in sorted(suppressed_files):
            if rel_path in scanned_rel_paths and rel_path not in observed_files:
                reported.append(
                    ArchitectureViolation(
                        path=rel_path,
                        line=1,
                        rule="stale-baseline",
                        message=f"File no longer violates {rule!r}; remove it from architecture_baseline.toml",
                    )
                )

    return sorted(reported, key=lambda v: (v.path, v.line, v.rule))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for verifying repository architecture invariants."""
    args = list(argv) if argv is not None else sys.argv[1:]
    repo_root = Path(__file__).resolve().parents[1]
    baseline_path = repo_root / "tools" / "architecture_baseline.toml"
    baseline = load_baseline(baseline_path)
    target_paths = (
        [repo_root / arg for arg in args] if args else [repo_root / "src" / "goe", repo_root / "tests" / "unit"]
    )
    violations = scan_paths(target_paths, repo_root=repo_root, baseline=baseline)
    if violations:
        for violation in violations:
            sys.stderr.write(f"{violation.path}:{violation.line}: [{violation.rule}] {violation.message}\n")
        sys.stderr.write(f"Architecture verification failed with {len(violations)} violation(s).\n")
        return 1
    sys.stdout.write("Architecture verification passed (0 unbaselined violations).\n")
    return 0


def _collect_python_files(paths: Sequence[Path]) -> list[Path]:
    """Expand files and directories into a sorted list of Python source files."""
    collected: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            collected.append(path)
        elif path.is_dir():
            collected.extend(sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts))
    return sorted(dict.fromkeys(collected))


def _scan_single_file(file_path: Path, *, rel_path: str) -> list[ArchitectureViolation]:
    """Run all AST and token checks on a single file."""
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel_path)
    violations: list[ArchitectureViolation] = []
    violations.extend(_check_raw_json(tree, rel_path=rel_path))
    violations.extend(_check_import_boundaries(tree, rel_path=rel_path))
    violations.extend(_check_nested_imports(tree, rel_path=rel_path))
    violations.extend(_check_member_ordering(tree, rel_path=rel_path))
    violations.extend(_check_inline_comments(source, tree, rel_path=rel_path))
    return violations


def _check_raw_json(tree: ast.AST, *, rel_path: str) -> list[ArchitectureViolation]:
    """Flag json.dumps, json.loads, and msgspec.json calls outside src/goe/serializers.py."""
    if rel_path == "src/goe/serializers.py":
        return []
    violations: list[ArchitectureViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted_expr_name(node.func)
            if dotted in {"json.dumps", "json.loads"} or (dotted is not None and dotted.startswith("msgspec.json.")):
                violations.append(
                    ArchitectureViolation(
                        path=rel_path,
                        line=getattr(node, "lineno", 1),
                        rule="raw-json",
                        message=f"Direct call to {dotted} is prohibited outside src/goe/serializers.py",
                    )
                )
    return violations


def _check_import_boundaries(tree: ast.AST, *, rel_path: str) -> list[ArchitectureViolation]:
    """Enforce sqlglot and oracledb package import boundaries within src/goe/."""
    if not rel_path.startswith("src/goe/"):
        return []
    allow_sqlglot = rel_path.startswith("src/goe/offload/sql_ast/")
    allow_oracledb = (
        rel_path.startswith(("src/goe/persistence/oracle/", "src/goe/offload/oracle/"))
        or rel_path == "src/goe/persistence/registry.py"
    )
    violations: list[ArchitectureViolation] = []

    for node in ast.walk(tree):
        imported_roots = _extract_import_roots(node)
        for root_name in imported_roots:
            if root_name == "sqlglot" and not allow_sqlglot:
                violations.append(
                    ArchitectureViolation(
                        path=rel_path,
                        line=getattr(node, "lineno", 1),
                        rule="sqlglot-boundary",
                        message="sqlglot imports are restricted to src/goe/offload/sql_ast/",
                    )
                )
            if root_name == "oracledb" and not allow_oracledb:
                violations.append(
                    ArchitectureViolation(
                        path=rel_path,
                        line=getattr(node, "lineno", 1),
                        rule="oracledb-boundary",
                        message="oracledb imports are restricted to src/goe/persistence/oracle/ and src/goe/offload/oracle/",
                    )
                )
    return violations


def _extract_import_roots(node: ast.AST) -> list[str]:
    """Return top-level package names referenced by an Import or ImportFrom AST node."""
    if isinstance(node, ast.Import):
        return [alias.name.split(".", maxsplit=1)[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module.split(".", maxsplit=1)[0]]
    return []


def _check_nested_imports(tree: ast.AST, *, rel_path: str) -> list[ArchitectureViolation]:
    """Flag import statements inside function or method bodies."""
    violations: list[ArchitectureViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    violations.append(
                        ArchitectureViolation(
                            path=rel_path,
                            line=getattr(child, "lineno", node.lineno),
                            rule="nested-import",
                            message=f"Function-scoped import inside {node.name!r} is prohibited",
                        )
                    )
    return violations


def _check_member_ordering(tree: ast.AST, *, rel_path: str) -> list[ArchitectureViolation]:
    """Verify public functions and methods precede private _ helpers in modules and classes."""
    violations: list[ArchitectureViolation] = []
    for scope in ast.walk(tree):
        if isinstance(scope, (ast.Module, ast.ClassDef)):
            funcs = [n for n in scope.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            seen_private = False
            for fn in funcs:
                if _is_private_name(fn.name):
                    seen_private = True
                elif seen_private:
                    scope_label = getattr(scope, "name", "<module>")
                    violations.append(
                        ArchitectureViolation(
                            path=rel_path,
                            line=fn.lineno,
                            rule="member-ordering",
                            message=f"Public function/method {fn.name!r} in {scope_label} appears after private helper",
                        )
                    )
    return violations


def _is_private_name(name: str) -> bool:
    """Return True if name is a single-underscore private identifier (excluding dunder methods)."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _check_inline_comments(source: str, tree: ast.AST, *, rel_path: str) -> list[ArchitectureViolation]:
    """Flag # comments located inside function or method line ranges."""
    func_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_lineno = getattr(node, "end_lineno", node.lineno)
            func_ranges.append((node.lineno, end_lineno))
    if not func_ranges:
        return []

    violations: list[ArchitectureViolation] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            line_no = tok.start[0]
            text = tok.string.strip()
            if text.startswith(("# type:", "# noqa", "# pragma:")):
                continue
            if any(start <= line_no <= end for start, end in func_ranges):
                violations.append(
                    ArchitectureViolation(
                        path=rel_path,
                        line=line_no,
                        rule="inline-comment",
                        message="Inline comments inside function/method bodies are prohibited; use docstrings",
                    )
                )
    return violations


def _dotted_expr_name(expr: ast.AST) -> str | None:
    """Reconstruct a dotted attribute path from an AST Name/Attribute chain."""
    parts: list[str] = []
    current: ast.AST | None = expr
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


if __name__ == "__main__":
    raise SystemExit(main())
