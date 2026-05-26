"""GitHub Agent Bridge."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


def _version_from_pyproject() -> str:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not pyproject.exists():
        return "0.0.0"
    return str(tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("version", "0.0.0"))


try:
    __version__ = version("github-agent-bridge")
except PackageNotFoundError:
    __version__ = _version_from_pyproject()
