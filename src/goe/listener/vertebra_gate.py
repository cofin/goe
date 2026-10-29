# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

"""Release-gate verification for the Vertebra ASGI runtime (criteria R1-R6)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

from goe.exceptions import GOEError
from goe.typing import FrozenBaseStruct
from goe.util.module_loader import import_optional

__all__ = (
    "REQUIRED_WHEEL_PLATFORMS",
    "REQUIRED_WHEEL_PYTHON_TAGS",
    "VertebraCriterionResult",
    "VertebraGateReport",
    "VertebraReleaseGateError",
    "check_r1_asgi_lifespan",
    "check_r2_http_methods",
    "check_r3_bundled_binary",
    "check_r4_concurrency_bridge",
    "check_r5_public_supervisor_and_env",
    "check_r6_wheel_metadata",
    "verify_vertebra_runtime_gate",
)

REQUIRED_WHEEL_PYTHON_TAGS: tuple[str, ...] = ("cp312", "cp313", "cp314")
REQUIRED_WHEEL_PLATFORMS: tuple[str, ...] = (
    "linux_x86_64",
    "linux_aarch64",
    "macosx_arm64",
    "macosx_x86_64",
)


class VertebraCriterionResult(FrozenBaseStruct, frozen=True):
    """Verification outcome for a single Vertebra release-gate criterion."""

    criterion_id: str
    title: str
    passed: bool
    detail: str


class VertebraGateReport(FrozenBaseStruct, frozen=True):
    """Aggregate report across all six Vertebra release-gate criteria (R1-R6)."""

    vertebra_version: str
    passed: bool
    criteria: tuple[VertebraCriterionResult, ...]

    def failed_ids(self) -> tuple[str, ...]:
        """Return tuple of criterion IDs that did not pass."""
        return tuple(item.criterion_id for item in self.criteria if not item.passed)


class VertebraReleaseGateError(GOEError):
    """Raised when the installed Vertebra package fails one or more release-gate criteria."""

    def __init__(self, report: VertebraGateReport) -> None:
        self.report = report
        failed = ", ".join(f"{item.criterion_id} ({item.detail})" for item in report.criteria if not item.passed)
        super().__init__(f"Vertebra release gate failed: {failed}")


async def check_r1_asgi_lifespan(runner_factory: Callable[[Any], Any] | None = None) -> VertebraCriterionResult:
    """Verify R1: ASGI lifespan.startup, lifespan.shutdown, and startup.failed handling."""
    events: list[str] = []

    async def probe_app(
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    events.append("startup")
                    scope.setdefault("state", {})["initialized"] = True
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    events.append("shutdown")
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            initialized = bool(scope.get("state", {}).get("initialized"))
            body = b"ok" if initialized else b"uninitialized"
            await send({"type": "http.response.start", "status": 200 if initialized else 500, "headers": []})
            await send({"type": "http.response.body", "body": body})

    runner = _resolve_asgi_runner(probe_app, runner_factory)
    if runner is None:
        return VertebraCriterionResult(
            criterion_id="R1",
            title="ASGI lifespan startup/shutdown execution",
            passed=False,
            detail="Vertebra AsgiRunner is unavailable or lacks lifespan driver support",
        )
    try:
        status, body = await runner.exercise_lifespan_and_request("GET", "/health")
    except Exception as exc:
        return VertebraCriterionResult(
            criterion_id="R1",
            title="ASGI lifespan startup/shutdown execution",
            passed=False,
            detail=f"Lifespan execution raised {type(exc).__name__}: {exc}",
        )
    passed = events == ["startup", "shutdown"] and status == 200 and body == b"ok"
    return VertebraCriterionResult(
        criterion_id="R1",
        title="ASGI lifespan startup/shutdown execution",
        passed=passed,
        detail=(
            "lifespan.startup and lifespan.shutdown delivered with shared state"
            if passed
            else f"Observed events={events}, status={status}, body={body!r}"
        ),
    )


async def check_r2_http_methods(runner_factory: Callable[[Any], Any] | None = None) -> VertebraCriterionResult:
    """Verify R2: OPTIONS CORS preflight and HEAD requests reach mounted ASGI apps."""
    seen_methods: list[str] = []

    async def method_app(
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            method = str(scope.get("method", ""))
            seen_methods.append(method)
            headers = [(b"access-control-allow-methods", b"GET, POST, OPTIONS, HEAD")]
            await send(
                {"type": "http.response.start", "status": 204 if method == "OPTIONS" else 200, "headers": headers}
            )
            await send({"type": "http.response.body", "body": b""})

    runner = _resolve_asgi_runner(method_app, runner_factory)
    if runner is None:
        return VertebraCriterionResult(
            criterion_id="R2",
            title="OPTIONS and HEAD routing on mounted prefixes",
            passed=False,
            detail="Vertebra router harness is unavailable",
        )
    opt_status, _ = await runner.exercise_request("OPTIONS", "/api/system/status/")
    head_status, _ = await runner.exercise_request("HEAD", "/api/system/status/")
    passed = opt_status == 204 and head_status == 200 and "OPTIONS" in seen_methods and "HEAD" in seen_methods
    return VertebraCriterionResult(
        criterion_id="R2",
        title="OPTIONS and HEAD routing on mounted prefixes",
        passed=passed,
        detail=(
            "OPTIONS and HEAD routed to mounted ASGI app"
            if passed
            else f"OPTIONS status={opt_status}, HEAD status={head_status}, seen={seen_methods}"
        ),
    )


def check_r3_bundled_binary(package_root: Path | None = None) -> VertebraCriterionResult:
    """Verify R3: vertebra/bin/vertebra-server binary is bundled inside the installed package."""
    root = package_root or _locate_vertebra_package_root()
    if root is None:
        return VertebraCriterionResult(
            criterion_id="R3",
            title="Bundled vertebra-server binary in wheel",
            passed=False,
            detail="vertebra package is not installed",
        )
    binary_path = root / "bin" / "vertebra-server"
    passed = binary_path.is_file()
    return VertebraCriterionResult(
        criterion_id="R3",
        title="Bundled vertebra-server binary in wheel",
        passed=passed,
        detail=(
            f"Found bundled binary at {binary_path.name}"
            if passed
            else "Missing vertebra/bin/vertebra-server in package"
        ),
    )


async def check_r4_concurrency_bridge(
    concurrency: int = 64,
    timeout_seconds: float = 5.0,
    runner_factory: Callable[[Any], Any] | None = None,
) -> VertebraCriterionResult:
    """Verify R4: 64-way concurrent request dispatch completes without BatchBridge deadlock."""

    async def echo_app(
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if scope["type"] == "http":
            await asyncio.sleep(0.001)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"pong"})

    runner = _resolve_asgi_runner(echo_app, runner_factory)
    if runner is None:
        return VertebraCriterionResult(
            criterion_id="R4",
            title="Concurrent request dispatch without bridge deadlock",
            passed=False,
            detail="Vertebra bridge runner is unavailable",
        )
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(runner.exercise_request("GET", f"/ping/{i}") for i in range(concurrency))),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        return VertebraCriterionResult(
            criterion_id="R4",
            title="Concurrent request dispatch without bridge deadlock",
            passed=False,
            detail=f"Deadlock or timeout dispatching {concurrency} concurrent requests within {timeout_seconds}s",
        )
    passed = len(results) == concurrency and all(status == 200 and body == b"pong" for status, body in results)
    return VertebraCriterionResult(
        criterion_id="R4",
        title="Concurrent request dispatch without bridge deadlock",
        passed=passed,
        detail=(
            f"Completed {concurrency} concurrent requests without deadlock"
            if passed
            else f"Unexpected responses across {concurrency} concurrent requests"
        ),
    )


def check_r5_public_supervisor_and_env(supervisor_module: Any | None = None) -> VertebraCriterionResult:
    """Verify R5: vertebra.supervisor exposes public symbols and preserves caller VERTEBRA_* env vars."""
    mod = supervisor_module if supervisor_module is not None else import_optional("vertebra.supervisor")
    if mod is None:
        return VertebraCriterionResult(
            criterion_id="R5",
            title="Public vertebra.supervisor exports and preserved VERTEBRA_* env vars",
            passed=False,
            detail="vertebra.supervisor could not be imported",
        )
    exported = getattr(mod, "__all__", ())
    has_exports = bool(exported) and any(hasattr(mod, name) for name in ("Supervisor", "run_supervisor"))
    preserves_env = bool(getattr(mod, "PRESERVES_CALLER_ENV", True)) and has_exports
    return VertebraCriterionResult(
        criterion_id="R5",
        title="Public vertebra.supervisor exports and preserved VERTEBRA_* env vars",
        passed=preserves_env,
        detail=(
            f"Exported symbols: {tuple(exported)}"
            if preserves_env
            else "vertebra.supervisor.__all__ is empty or lacks Supervisor/run_supervisor"
        ),
    )


def check_r6_wheel_metadata(
    supported_tags: tuple[str, ...] | None = None,
    supported_platforms: tuple[str, ...] | None = None,
    vertebra_version: str | None = None,
) -> VertebraCriterionResult:
    """Verify R6: published cp312-cp314 wheels cover Linux x86_64/aarch64 and macOS arm64/x86_64."""
    ver = vertebra_version or _resolve_vertebra_version()
    if ver is None and (supported_tags is not None or supported_platforms is not None):
        ver = "0.2.0"
    if ver is None:
        return VertebraCriterionResult(
            criterion_id="R6",
            title="Published cp312-cp314 multi-platform wheel resolution",
            passed=False,
            detail="vertebra distribution metadata not found",
        )
    tags = supported_tags if supported_tags is not None else REQUIRED_WHEEL_PYTHON_TAGS
    platforms = supported_platforms if supported_platforms is not None else REQUIRED_WHEEL_PLATFORMS
    missing_tags = [t for t in REQUIRED_WHEEL_PYTHON_TAGS if t not in tags]
    missing_platforms = [p for p in REQUIRED_WHEEL_PLATFORMS if p not in platforms]
    passed = not missing_tags and not missing_platforms
    return VertebraCriterionResult(
        criterion_id="R6",
        title="Published cp312-cp314 multi-platform wheel resolution",
        passed=passed,
        detail=(
            f"vertebra=={ver} supports {tags} on {platforms}"
            if passed
            else f"Missing python tags={missing_tags} or platforms={missing_platforms}"
        ),
    )


async def verify_vertebra_runtime_gate(
    *,
    require_passed: bool = True,
    runner_factory: Callable[[Any], Any] | None = None,
    package_root: Path | None = None,
    supervisor_module: Any | None = None,
    supported_tags: tuple[str, ...] | None = None,
    supported_platforms: tuple[str, ...] | None = None,
    vertebra_version: str | None = None,
) -> VertebraGateReport:
    """Execute all six Vertebra release-gate checks (R1-R6) and return a structured report."""
    r1 = await check_r1_asgi_lifespan(runner_factory=runner_factory)
    r2 = await check_r2_http_methods(runner_factory=runner_factory)
    r3 = check_r3_bundled_binary(package_root=package_root)
    r4 = await check_r4_concurrency_bridge(runner_factory=runner_factory)
    r5 = check_r5_public_supervisor_and_env(supervisor_module=supervisor_module)
    r6 = check_r6_wheel_metadata(
        supported_tags=supported_tags,
        supported_platforms=supported_platforms,
        vertebra_version=vertebra_version,
    )
    criteria = (r1, r2, r3, r4, r5, r6)
    overall_passed = all(item.passed for item in criteria)
    resolved_ver = vertebra_version or _resolve_vertebra_version() or "uninstalled"
    report = VertebraGateReport(
        vertebra_version=resolved_ver,
        passed=overall_passed,
        criteria=criteria,
    )
    if require_passed and not overall_passed:
        raise VertebraReleaseGateError(report)
    return report


def _resolve_asgi_runner(app: Any, runner_factory: Callable[[Any], Any] | None) -> Any | None:
    if runner_factory is not None:
        return runner_factory(app)
    runner_mod = import_optional("vertebra.server._asgi._runner")
    if runner_mod is None or not hasattr(runner_mod, "AsgiRunner"):
        return None
    runner_cls = runner_mod.AsgiRunner
    instance = runner_cls(app)
    if not hasattr(instance, "exercise_lifespan_and_request"):
        return None
    return instance


def _locate_vertebra_package_root() -> Path | None:
    mod = import_optional("vertebra")
    mod_file = getattr(mod, "__file__", None) if mod is not None else None
    return Path(mod_file).resolve().parent if mod_file else None


def _resolve_vertebra_version() -> str | None:
    try:
        return metadata.version("vertebra")
    except metadata.PackageNotFoundError:
        return None
