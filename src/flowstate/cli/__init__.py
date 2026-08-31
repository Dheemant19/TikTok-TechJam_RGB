from __future__ import annotations

from flowstate.cli.knowledge import app as knowledge_app
from flowstate.cli.workflow import app

app.add_typer(knowledge_app, name="knowledge")


def main() -> None:
    app()
