from __future__ import annotations

from pathlib import Path
from typing import Any


PROC_ROOT = Path("/proc")


def process_exists(pid: int, proc_root: Path = PROC_ROOT) -> bool:
    return (proc_root / str(pid)).exists()


def process_cmd(pid: int, proc_root: Path = PROC_ROOT) -> str:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def process_stat(pid: int, proc_root: Path = PROC_ROOT) -> dict[str, Any] | None:
    try:
        raw = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    close = raw.rfind(")")
    if close < 0:
        return None
    fields = raw[close + 2 :].split()
    try:
        return {
            "state": fields[0],
            "ppid": int(fields[1]),
            "cpu_ticks": int(fields[11]) + int(fields[12]),
        }
    except (IndexError, ValueError):
        return None


def process_io(pid: int, proc_root: Path = PROC_ROOT) -> dict[str, int] | None:
    try:
        raw = (proc_root / str(pid) / "io").read_text(encoding="utf-8")
    except OSError:
        return None
    values: dict[str, int] = {}
    for line in raw.splitlines():
        key, _, value = line.partition(":")
        if key in {"read_bytes", "write_bytes"}:
            try:
                values[key] = int(value.strip())
            except ValueError:
                continue
    return values or None


def direct_child_pids(pid: int, proc_root: Path = PROC_ROOT) -> list[int]:
    children: list[int] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return children
    for entry in entries:
        if not entry.name.isdigit():
            continue
        child_pid = int(entry.name)
        stat = process_stat(child_pid, proc_root=proc_root)
        if stat and stat.get("ppid") == pid:
            children.append(child_pid)
    return sorted(children)


def inspect_process(pid: int, proc_root: Path = PROC_ROOT, *, include_children: bool = False, max_depth: int = 2) -> dict[str, Any] | None:
    stat = process_stat(pid, proc_root=proc_root)
    if stat is None:
        return None
    sample: dict[str, Any] = {
        "pid": pid,
        "ppid": stat["ppid"],
        "state": stat["state"],
        "cmd": process_cmd(pid, proc_root=proc_root),
        "cpu_ticks": stat["cpu_ticks"],
        "io_bytes": process_io(pid, proc_root=proc_root),
    }
    if include_children:
        sample["children"] = []
        if max_depth > 0:
            sample["children"] = [
                child
                for child_pid in direct_child_pids(pid, proc_root=proc_root)
                if (child := inspect_process(child_pid, proc_root=proc_root, include_children=True, max_depth=max_depth - 1)) is not None
            ]
    return sample


def direct_children(pid: int, proc_root: Path = PROC_ROOT) -> list[dict[str, Any]]:
    return [
        child
        for child_pid in direct_child_pids(pid, proc_root=proc_root)
        if (child := inspect_process(child_pid, proc_root=proc_root, include_children=True)) is not None
    ]
