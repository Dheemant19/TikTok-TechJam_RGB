from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from flowstate.knowledge.config import load_knowledge_config
from flowstate.knowledge.ingestion import ManifestValidationFailure, validate_manifest
from flowstate.knowledge.runtime import KnowledgeRuntime

app = typer.Typer(help="Validate, ingest, inspect, and serve the Research Knowledge MCP.", no_args_is_help=True)


def emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True))


@app.command("validate")
def validate_command(
    file: Annotated[Path, typer.Option("--file")] = Path("data/research/curated_papers.json"),
    config: Annotated[Path, typer.Option("--config")] = Path("configs/knowledge/research.yaml"),
) -> None:
    """Validate fields and duplicates without opening or mutating SQLite."""
    knowledge_config = load_knowledge_config(config)
    target = file if file.is_absolute() else Path.cwd() / file
    try:
        manifest = validate_manifest(target, knowledge_config.curated_source.expected_paper_count)
    except ManifestValidationFailure as error:
        emit({"status": "invalid", "file": str(target), "errors": error.errors, "database_mutated": False})
        raise typer.Exit(2) from error
    emit({
        "status": "valid", "file": str(target), "schema_version": manifest.schema_version,
        "paper_count": len(manifest.papers), "unique_paper_ids": len({paper.paper_id for paper in manifest.papers}),
        "database_mutated": False,
    })


@app.command("ingest-curated")
def ingest_curated_command(
    file: Annotated[Path, typer.Option("--file")] = Path("data/research/curated_papers.json"),
    config: Annotated[Path, typer.Option("--config")] = Path("configs/knowledge/research.yaml"),
    enrich: Annotated[bool, typer.Option("--enrich/--no-enrich")] = False,
    resolve_code: Annotated[bool, typer.Option("--resolve-code/--no-resolve-code")] = False,
) -> None:
    runtime = KnowledgeRuntime(config)

    async def run() -> None:
        target = file if file.is_absolute() else Path.cwd() / file
        receipts = await runtime.ingestion.ingest_curated(target, enrich=enrich, resolve_code=resolve_code)
        emit({
            "status": "completed" if all(item.outcome != "failed" for item in receipts) else "failed",
            "receipts": [item.model_dump(mode="json") for item in receipts],
            "counts": runtime.store.counts(),
        })
        await runtime.close()
        if any(item.outcome == "failed" for item in receipts):
            raise typer.Exit(1)

    asyncio.run(run())


@app.command("ingest-scheduled")
def ingest_scheduled_command(
    once: Annotated[bool, typer.Option("--once")] = True,
    config: Annotated[Path, typer.Option("--config")] = Path("configs/knowledge/research.yaml"),
) -> None:
    if not once:
        raise typer.BadParameter("only the restart-safe --once mode is supported")
    runtime = KnowledgeRuntime(config)

    async def run() -> None:
        receipts = await runtime.ingestion.ingest_scheduled(once=True)
        emit({"status": "completed", "receipts": [item.model_dump(mode="json") for item in receipts]})
        await runtime.close()

    asyncio.run(run())


@app.command("status")
def status_command(
    config: Annotated[Path, typer.Option("--config")] = Path("configs/knowledge/research.yaml"),
) -> None:
    runtime = KnowledgeRuntime(config)
    emit({
        "status": "ready", "database": str(runtime.config.storage.database),
        "counts": runtime.store.counts(), "providers": {
            "huggingface_papers": runtime.huggingface is not None,
            "github": runtime.github is not None,
            "papers_with_code": runtime.papers_with_code.enabled,
        },
    })


@app.command("reindex")
def reindex_command(
    config: Annotated[Path, typer.Option("--config")] = Path("configs/knowledge/research.yaml"),
) -> None:
    runtime = KnowledgeRuntime(config)
    emit({"status": "completed", "fts_records": runtime.store.reindex_fts()})


@app.command("serve")
def serve_command(
    transport: Annotated[str, typer.Option("--transport")] = "stdio",
) -> None:
    if transport not in {"stdio", "streamable-http"}:
        raise typer.BadParameter("transport must be stdio or streamable-http")
    from flowstate.mcp.server import get_application
    get_application().mcp.run(transport=transport)
