"""Run the managed DOCX renderer with a Windows LibreOffice URI fix."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def find_default_renderer() -> Path:
    candidates = sorted(
        (Path.home() / ".codex" / "plugins" / "cache").glob(
            "*/documents/*/skills/documents/render_docx.py"
        ),
        reverse=True,
    )
    if not candidates:
        raise RuntimeError(
            "managed DOCX renderer not found; set CODEX_DOCX_RENDERER to render_docx.py"
        )
    return candidates[0]


def main() -> None:
    configured = os.getenv("CODEX_DOCX_RENDERER")
    renderer_path = Path(configured) if configured else find_default_renderer()
    spec = importlib.util.spec_from_file_location("codex_managed_render_docx", renderer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load managed renderer: {renderer_path}")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    original_run_cmd = renderer._run_cmd

    def run_cmd(command, **kwargs):
        normalized = []
        for argument in command:
            prefix = "-env:UserInstallation=file://"
            if argument.startswith(prefix):
                profile = argument[len(prefix):]
                argument = "-env:UserInstallation=" + Path(profile).resolve().as_uri()
            normalized.append(argument)
        return original_run_cmd(normalized, **kwargs)

    renderer._run_cmd = run_cmd
    renderer.main()


if __name__ == "__main__":
    main()
