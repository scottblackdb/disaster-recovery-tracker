#!/usr/bin/env python3
"""Workshop setup script for the Disaster Recovery Tracker lab.

Creates an autoscaling Lakebase (Postgres) project and provisions workspace users.
Requires: databricks-sdk  (pip install databricks-sdk)
"""

import argparse
import configparser
import re
import sys
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

try:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.common.lro import LroOptions
    from databricks.sdk.errors import AlreadyExists, NotFound, ResourceAlreadyExists
    from databricks.sdk.service import iam, postgres
    from databricks.sdk.service.catalog import PermissionsChange, Privilege, VolumeType
    from databricks.sdk.service.sql import (
        ExecuteStatementRequestOnWaitTimeout,
        StatementState,
    )
except ImportError:
    print("Error: databricks-sdk is required.  pip install databricks-sdk")
    sys.exit(1)


# Backend (backend/config.py) reads files from VOLUME_PATH, defaulting to
# /Volumes/fema/default/filestore. Keep these defaults in sync with that.
DEFAULT_CATALOG = "fema"
DEFAULT_BRONZE_SCHEMA = "bronze"
DEFAULT_SILVER_SCHEMA = "silver"
DEFAULT_VOLUME_SCHEMA = "default"
DEFAULT_VOLUME_NAME = "filestore"

# Built-in account group (Unity Catalog principal and Permissions API ``group_name``;
# UI label: All account users).
ALL_USERS_PRINCIPAL = "account users"


# ---------------------------------------------------------------------------
# Profile selection
# ---------------------------------------------------------------------------

def get_profiles() -> list[str]:
    cfg_path = Path.home() / ".databrickscfg"
    if not cfg_path.exists():
        print("Error: ~/.databrickscfg not found. Run 'databricks configure' first.")
        sys.exit(1)
    config = configparser.RawConfigParser()
    config.read(cfg_path)
    return config.sections()


def select_profile(profiles: list[str], profile_arg: str | None) -> str:
    if profile_arg:
        if profile_arg not in profiles:
            print(f"Error: profile '{profile_arg}' not found in ~/.databrickscfg")
            print(f"Available: {', '.join(profiles)}")
            sys.exit(1)
        return profile_arg

    if len(profiles) == 1:
        print(f"Using profile: {profiles[0]}")
        return profiles[0]

    print("\nAvailable Databricks profiles:")
    for i, p in enumerate(profiles, 1):
        print(f"  {i}. {p}")

    prompt = f"Please enter a number between 1 and {len(profiles)}"
    while True:
        try:
            choice = input(f"\nSelect profile [1-{len(profiles)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(profiles):
                return profiles[idx]
        except ValueError:
            pass
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)
        print(prompt)


# ---------------------------------------------------------------------------
# Lakebase
# ---------------------------------------------------------------------------

def _to_project_id(name: str) -> str:
    """Sanitize a display name into a valid Lakebase project ID.

    Must be 1-63 chars, start with a lowercase letter, contain only
    lowercase letters, numbers, and hyphens.
    """
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug or not slug[0].isalpha():
        slug = "ws-" + slug
    return slug[:63]


def _lakebase_project_resource_name(project_id: str) -> str:
    """Full Lakebase project path required by get_project (projects/{project_id})."""
    if project_id.startswith("projects/"):
        return project_id
    return f"projects/{project_id}"


def _lakebase_project_exists(w: WorkspaceClient, project_id: str) -> bool:
    """Return True if a Lakebase project with this ID already exists."""
    try:
        w.postgres.get_project(name=_lakebase_project_resource_name(project_id))
        return True
    except NotFound:
        return False
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("not found", "does not exist", "404")):
            return False
        raise


def _grant_lakebase_project_manage_all_account_users(w: WorkspaceClient, project_id: str) -> None:
    """Grant Lakebase project ACL ``CAN_MANAGE`` (Manage in UI) to All account users.

    Uses the workspace Permissions API (``database-projects``), not Unity Catalog grants.
    See https://docs.databricks.com/aws/en/oltp/projects/grant-permissions-programmatically
    """
    try:
        w.permissions.update(
            request_object_type="database-projects",
            request_object_id=project_id,
            access_control_list=[
                iam.AccessControlRequest(
                    group_name=ALL_USERS_PRINCIPAL,
                    permission_level=iam.PermissionLevel.CAN_MANAGE,
                )
            ],
        )
        print(
            f"  [+] Lakebase project '{project_id}': CAN_MANAGE for "
            f"group '{ALL_USERS_PRINCIPAL}' (All account users)"
        )
    except Exception as e:
        print(f"  [!] Lakebase project permissions on '{project_id}' — {e}")
        sys.exit(1)


def create_lakebase(
    w: WorkspaceClient,
    display_name: str,
    pg_version: int = 17,
    *,
    skip_if_exists: bool = False,
) -> None:
    project_id = _to_project_id(display_name)
    if skip_if_exists and _lakebase_project_exists(w, project_id):
        print(
            f"\nSkipping Lakebase project '{display_name}' (id: {project_id}) — already exists."
        )
        return

    print(f"\nCreating autoscaling Lakebase project '{display_name}' (id: {project_id}, pg{pg_version})...")

    project = postgres.Project(
        spec=postgres.ProjectSpec(
            display_name=display_name,
            pg_version=pg_version,
        )
    )

    try:
        op = w.postgres.create_project(project=project, project_id=project_id)
    except (AlreadyExists, ResourceAlreadyExists):
        print(f"  Lakebase project '{project_id}' already exists, skipping.")
        if not skip_if_exists:
            _grant_lakebase_project_manage_all_account_users(w, project_id)
        return
    except Exception as e:
        if _is_already_exists(e):
            print(f"  Lakebase project '{project_id}' already exists, skipping.")
            if not skip_if_exists:
                _grant_lakebase_project_manage_all_account_users(w, project_id)
            return
        print(f"  Error: {e}")
        sys.exit(1)

    print("  Waiting for Lakebase to become ready", end="", flush=True)
    try:
        result = op.wait(LroOptions(timeout=timedelta(seconds=600)))
        print()
        name = result.spec.display_name if result and result.spec else project_id
        print(f"  Ready: {name}")
        _grant_lakebase_project_manage_all_account_users(w, project_id)
    except Exception as e:
        print(f"\n  Operation ended: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Unity Catalog (catalog, schemas, volume referenced by the backend)
# ---------------------------------------------------------------------------

def _is_already_exists(exc: Exception) -> bool:
    if isinstance(exc, (AlreadyExists, ResourceAlreadyExists)):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in ("already exists", "conflict", "409", "uniqueness"))


def _create_idempotent(
    create_fn: Callable[[], None],
    *,
    created_msg: str,
    exists_msg: str,
    error_label: str,
) -> None:
    """Run a create call; treat 'already exists' as success, exit on other errors."""
    try:
        create_fn()
        print(f"  [+] {created_msg}")
    except (AlreadyExists, ResourceAlreadyExists):
        print(f"  [~] {exists_msg}")
    except Exception as e:
        if _is_already_exists(e):
            print(f"  [~] {exists_msg}")
        else:
            print(f"  [!] {error_label} — {e}")
            sys.exit(1)


def _sql_identifier(name: str, *, label: str) -> str:
    """Validate a Unity Catalog identifier for safe use in SQL."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        print(f"Error: invalid {label} {name!r} for SQL (use letters, numbers, _, -)")
        sys.exit(1)
    return name


def _resolve_sql_warehouse_id(w: WorkspaceClient, warehouse_id: str | None) -> str:
    if warehouse_id:
        return warehouse_id
    for wh in w.warehouses.list():
        if wh.id:
            return wh.id
    print("Error: no SQL warehouse found; create one or pass --warehouse-id")
    sys.exit(1)


def _execute_sql_statement(w: WorkspaceClient, warehouse_id: str, statement: str) -> None:
    """Run a SQL statement on a SQL warehouse; exit on failure."""
    resp = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
    )
    deadline = time.time() + 120
    while resp.status and resp.status.state not in (
        StatementState.SUCCEEDED,
        StatementState.FAILED,
        StatementState.CANCELED,
        StatementState.CLOSED,
    ):
        if time.time() >= deadline:
            break
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)

    if resp.status is None:
        print("  [!] SQL statement execution: missing status")
        sys.exit(1)
    if resp.status.state != StatementState.SUCCEEDED:
        err = resp.status.error.as_dict() if resp.status.error else {}
        print(f"  [!] SQL failed: state={resp.status.state} detail={err}")
        sys.exit(1)


def _create_catalog_if_not_exists_sql(
    w: WorkspaceClient,
    catalog_name: str,
    warehouse_id: str | None,
) -> None:
    safe_name = _sql_identifier(catalog_name, label="catalog name")
    wh_id = _resolve_sql_warehouse_id(w, warehouse_id)
    statement = f"CREATE CATALOG IF NOT EXISTS {safe_name}"
    _execute_sql_statement(w, wh_id, statement)
    print(f"  [+] catalog '{catalog_name}' ({statement})")


def _first_external_location_url(w: WorkspaceClient) -> str | None:
    """Return the URL of the first user-defined external location, or None.

    Skips workspace-internal/auto-managed locations (the metastore's
    `__databricks_managed_storage_location` cannot be used as a catalog
    MANAGED LOCATION — it's reserved for Default Storage).
    """
    try:
        for loc in w.external_locations.list():
            if not loc.url:
                continue
            if loc.name and loc.name.startswith("__databricks_managed_"):
                continue
            return loc.url
    except Exception as e:
        print(f"  Note: could not list external locations: {e}")
    return None


def create_uc_resources(
    w: WorkspaceClient,
    catalog_name: str,
    bronze_schema: str = DEFAULT_BRONZE_SCHEMA,
    silver_schema: str = DEFAULT_SILVER_SCHEMA,
    volume_schema: str = DEFAULT_VOLUME_SCHEMA,
    volume_name: str = DEFAULT_VOLUME_NAME,
    *,
    warehouse_id: str | None = None,
) -> None:
    """Create the catalog, bronze/silver/volume schemas, the managed volume the
    backend uses, grant read access on the catalog to all account users, and
    grant MANAGE on the volume to all account users."""
    print(f"\nCreating Unity Catalog resources (catalog: {catalog_name})...")

    # Catalog. Workspaces without a metastore storage root require an explicit
    # MANAGED LOCATION; use the first user-defined external location when present.
    # Otherwise use CREATE CATALOG IF NOT EXISTS via SQL (metastore default storage).
    storage_root = _first_external_location_url(w)
    if storage_root:
        _create_idempotent(
            lambda: w.catalogs.create(name=catalog_name, storage_root=storage_root),
            created_msg=f"catalog '{catalog_name}' (storage_root={storage_root})",
            exists_msg=f"catalog '{catalog_name}' (already exists)",
            error_label=f"catalog '{catalog_name}'",
        )
    else:
        _create_catalog_if_not_exists_sql(w, catalog_name, warehouse_id)

    # Schemas (bronze + silver + the schema that holds the volume; UC auto-creates
    # 'default' but we attempt it idempotently in case the catalog was created without one)
    for schema in (bronze_schema, silver_schema, volume_schema):
        _create_idempotent(
            lambda s=schema: w.schemas.create(name=s, catalog_name=catalog_name),
            created_msg=f"schema '{catalog_name}.{schema}'",
            exists_msg=f"schema '{catalog_name}.{schema}' (already exists)",
            error_label=f"schema '{catalog_name}.{schema}'",
        )

    # Grant USE CATALOG / USE SCHEMA / SELECT on the catalog to every workspace
    # user so workshop participants can browse and query fema.bronze.*, fema.silver.*.
    try:
        w.grants.update(
            securable_type="catalog",
            full_name=catalog_name,
            changes=[
                PermissionsChange(
                    principal=ALL_USERS_PRINCIPAL,
                    add=[Privilege.USE_CATALOG, Privilege.USE_SCHEMA, Privilege.SELECT],
                )
            ],
        )
        print(f"  [+] grants on '{catalog_name}' to '{ALL_USERS_PRINCIPAL}': USE CATALOG, USE SCHEMA, SELECT")
    except Exception as e:
        print(f"  [!] grant on '{catalog_name}' — {e}")
        sys.exit(1)

    # Managed volume referenced by backend VOLUME_PATH
    full_volume = f"/Volumes/{catalog_name}/{volume_schema}/{volume_name}"
    _create_idempotent(
        lambda: w.volumes.create(
            catalog_name=catalog_name,
            schema_name=volume_schema,
            name=volume_name,
            volume_type=VolumeType.MANAGED,
        ),
        created_msg=f"volume '{full_volume}'",
        exists_msg=f"volume '{full_volume}' (already exists)",
        error_label=f"volume '{full_volume}'",
    )

    volume_securable_name = f"{catalog_name}.{volume_schema}.{volume_name}"
    try:
        w.grants.update(
            securable_type="volume",
            full_name=volume_securable_name,
            changes=[
                PermissionsChange(
                    principal=ALL_USERS_PRINCIPAL,
                    add=[Privilege.MANAGE],
                )
            ],
        )
        print(
            f"  [+] volume grant on '{volume_securable_name}' to "
            f"'{ALL_USERS_PRINCIPAL}': MANAGE"
        )
    except Exception as e:
        print(f"  [!] volume grant on '{volume_securable_name}' — {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def provision_users(w: WorkspaceClient, users_file: str) -> None:
    path = Path(users_file)
    if not path.exists():
        print(f"Error: users file '{users_file}' not found.")
        sys.exit(1)

    emails = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not emails:
        print("No email addresses found in file.")
        return

    print(f"\nProvisioning {len(emails)} user(s)...")

    success = skipped = failed = 0
    for email in emails:
        display = email.split("@")[0]
        try:
            w.users.create(
                user_name=email,
                display_name=display,
                active=True,
                emails=[iam.ComplexValue(value=email, primary=True)],
            )
            print(f"  [+] {email}")
            success += 1
        except Exception as e:
            if _is_already_exists(e):
                print(f"  [~] {email} (already exists)")
                skipped += 1
            else:
                print(f"  [!] {email} — {e}")
                failed += 1

    print(f"\n  Users: {success} created, {skipped} already existed, {failed} failed.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up the Disaster Recovery Tracker workshop environment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Full setup — Lakebase + UC catalog/schemas/volume + users:
  python setup_workshop.py --users-file participants.txt

  # Lakebase only:
  python setup_workshop.py --lakebase-only

  # Unity Catalog only (catalog, bronze schema, default schema, filestore volume):
  python setup_workshop.py --uc-only

  # Users only:
  python setup_workshop.py --users-only --users-file participants.txt

  # Specify profile and custom name:
  python setup_workshop.py --profile fema --lakebase-name "dr-workshop" --users-file participants.txt

  # Re-run full setup but leave an existing Lakebase project untouched:
  python setup_workshop.py --skip-lakebase-if-exists --users-file participants.txt
        """,
    )

    parser.add_argument(
        "--profile", "-p",
        metavar="PROFILE",
        help="Databricks CLI profile from ~/.databrickscfg (prompts if not set)",
    )
    parser.add_argument(
        "--users-file", "-u",
        metavar="FILE",
        help="Text file with one user email address per line (# lines ignored)",
    )
    parser.add_argument(
        "--lakebase-name",
        default="disaster-recovery-tracker",
        metavar="NAME",
        help="Lakebase display name (default: disaster-recovery-tracker)",
    )
    parser.add_argument(
        "--pg-version",
        type=int,
        default=17,
        choices=[16, 17],
        metavar="VER",
        help="PostgreSQL major version (16 or 17, default: 17)",
    )
    parser.add_argument(
        "--catalog",
        default=DEFAULT_CATALOG,
        metavar="NAME",
        help=f"Unity Catalog name (default: {DEFAULT_CATALOG})",
    )
    parser.add_argument(
        "--warehouse-id",
        metavar="ID",
        help=(
            "SQL warehouse ID for CREATE CATALOG IF NOT EXISTS when no external "
            "location is available (default: first warehouse in the workspace)"
        ),
    )
    parser.add_argument(
        "--skip-lakebase-if-exists",
        action="store_true",
        help=(
            "If the Lakebase project already exists, skip creation and permission "
            "updates (default: still apply CAN_MANAGE for All account users)"
        ),
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--lakebase-only",
        action="store_true",
        help="Only create the Lakebase project",
    )
    mode.add_argument(
        "--users-only",
        action="store_true",
        help="Only provision users",
    )
    mode.add_argument(
        "--uc-only",
        action="store_true",
        help="Only create the Unity Catalog catalog/schemas/volume",
    )

    args = parser.parse_args()

    needs_users_file = not (args.lakebase_only or args.uc_only)
    if needs_users_file and not args.users_file:
        parser.error("--users-file is required unless --lakebase-only or --uc-only is specified")

    profiles = get_profiles()
    profile = select_profile(profiles, args.profile)
    print(f"Profile: {profile}")

    w = WorkspaceClient(profile=profile)

    lakebase_kwargs = {"skip_if_exists": args.skip_lakebase_if_exists}

    if args.users_only:
        provision_users(w, args.users_file)
    elif args.lakebase_only:
        create_lakebase(w, args.lakebase_name, args.pg_version, **lakebase_kwargs)
    elif args.uc_only:
        create_uc_resources(w, args.catalog, warehouse_id=args.warehouse_id)
    else:
        create_lakebase(w, args.lakebase_name, args.pg_version, **lakebase_kwargs)
        create_uc_resources(w, args.catalog, warehouse_id=args.warehouse_id)
        provision_users(w, args.users_file)

    print("\nWorkshop setup complete.")


if __name__ == "__main__":
    main()
