"""Guard the compose file's environment wiring.

The containers get their configuration from the local ``.env`` file, which is
gitignored. Without ``env_file`` on a service, compose only uses that file for
``${VAR}`` substitution, so a key like ``OPENROUTER_API_KEY`` or
``EDGAR_USER_AGENT`` is silently absent inside the container.
"""

from __future__ import annotations

from pathlib import Path

COMPOSE_PATH = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def _service_block(service: str) -> str:
    """Return the YAML lines belonging to one top-level service."""
    lines = COMPOSE_PATH.read_text(encoding="utf-8").splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == f"{service}:"),
        None,
    )
    assert start is not None, f"service {service!r} is missing from docker-compose.yml"

    block: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        block.append(line)
    return "\n".join(block)


def test_containers_receive_the_local_environment_file() -> None:
    for service in ("app", "worker"):
        block = _service_block(service)
        assert "env_file:" in block, f"{service} does not load an env_file"
        assert ".env" in block, f"{service} does not load .env"
