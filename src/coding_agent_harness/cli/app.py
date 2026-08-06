from __future__ import annotations

from pathlib import Path
from uuid import UUID

import typer


def _default_runtime_factory():
    from coding_agent_harness.composition import build_demo_runtime

    return build_demo_runtime()


def _default_persistent_runtime_factory():
    from coding_agent_harness.composition import build_default_real_runtime

    return build_default_real_runtime()


def _default_credential_store_factory():
    import keyring

    from coding_agent_harness.adapters.credentials.keyring_store import KeyringCredentialStore

    return KeyringCredentialStore(backend=keyring)


def _default_real_provider_factory():
    return None


def _task_uuid(raw: str) -> UUID:
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError):
        raise ValueError("invalid task id") from None
    if str(parsed) != raw or parsed.version != 4:
        raise ValueError("invalid task id")
    return parsed


def _render(view) -> None:
    status = view.status.value if hasattr(view.status, "value") else str(view.status)
    typer.echo(f"task_id: {view.task_id}")
    typer.echo(f"status: {status}")
    typer.echo(f"summary: {view.safe_summary}")


def build_cli(*, runtime_factory=None, demo_runtime_factory=None, persistent_runtime_factory=None, credential_store_factory=None, real_provider_factory=None) -> typer.Typer:
    if runtime_factory is not None:
        demo_runtime_factory = runtime_factory
        persistent_runtime_factory = runtime_factory
    demo_runtime_factory = demo_runtime_factory or _default_runtime_factory
    persistent_runtime_factory = persistent_runtime_factory or _default_persistent_runtime_factory
    credential_precheck = credential_store_factory is not None
    credential_store_factory = credential_store_factory or _default_credential_store_factory
    real_provider_factory = real_provider_factory or _default_real_provider_factory
    cli = typer.Typer(no_args_is_help=True, add_completion=False, help="Governed local coding agent harness.")
    key_cli = typer.Typer(no_args_is_help=True, help="Manage the provider key.")

    @cli.command()
    def run(
        repository: str,
        task_description: str,
        demo: bool = typer.Option(False, "--demo"),
        trust_repo: bool = typer.Option(False, "--trust-repo"),
    ) -> None:
        path = Path(repository)
        if not path.exists() or not path.is_dir():
            typer.echo("repository is invalid")
            raise typer.Exit(2)
        path = path.resolve(strict=True)
        if not demo and credential_precheck:
            try:
                store = credential_store_factory()
                if not store.status():
                    typer.echo("credential is not configured")
                    raise typer.Exit(2)
                if real_provider_factory is not _default_real_provider_factory:
                    real_provider_factory()
            except typer.Exit:
                raise
            except Exception:
                typer.echo("provider is unavailable")
                raise typer.Exit(2) from None
        try:
            factory = demo_runtime_factory if demo else persistent_runtime_factory
            view = factory().run(repository=path, task_description=task_description, mode="demo" if demo else "real", trust_repo=trust_repo)
        except Exception:
            typer.echo("task could not be started")
            raise typer.Exit(2) from None
        _render(view)

    @cli.command()
    def status(task_id: str) -> None:
        try:
            parsed = _task_uuid(task_id)
        except ValueError:
            typer.echo("invalid task id")
            raise typer.Exit(2) from None
        try:
            view = persistent_runtime_factory().status(parsed)
        except KeyError:
            typer.echo("task not found")
            raise typer.Exit(2) from None
        except Exception:
            typer.echo("task status unavailable")
            raise typer.Exit(2) from None
        _render(view)

    @cli.command()
    def resume(task_id: str) -> None:
        try:
            parsed = _task_uuid(task_id)
        except ValueError:
            typer.echo("invalid task id")
            raise typer.Exit(2) from None
        try:
            view = persistent_runtime_factory().resume(parsed)
        except (KeyError, ValueError):
            typer.echo("task cannot be resumed")
            raise typer.Exit(2) from None
        except Exception:
            typer.echo("task resume unavailable")
            raise typer.Exit(2) from None
        _render(view)

    @key_cli.command("set")
    def key_set() -> None:
        value = typer.prompt("Key", hide_input=True)
        try:
            credential_store_factory().set(value)
        except Exception:
            typer.echo("key could not be stored")
            raise typer.Exit(2) from None
        typer.echo("configured")

    @key_cli.command("status")
    def key_status() -> None:
        try:
            configured = credential_store_factory().status()
        except Exception:
            typer.echo("key status unavailable")
            raise typer.Exit(2) from None
        typer.echo("configured" if configured else "not configured")

    @key_cli.command("update")
    def key_update() -> None:
        value = typer.prompt("Key", hide_input=True)
        try:
            credential_store_factory().update(value)
        except Exception:
            typer.echo("key could not be updated")
            raise typer.Exit(2) from None
        typer.echo("configured")

    @key_cli.command("clear")
    def key_clear() -> None:
        try:
            credential_store_factory().clear()
        except Exception:
            typer.echo("key could not be cleared")
            raise typer.Exit(2) from None
        typer.echo("not configured")

    cli.add_typer(key_cli, name="key")
    return cli


app = build_cli()


def main() -> None:
    app()
