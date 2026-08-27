from __future__ import annotations

from rigor_rs.cli.knowledge import app as knowledge_app
from rigor_rs.cli.workflow import app

app.add_typer(knowledge_app, name="knowledge")


def main() -> None:
    app()
