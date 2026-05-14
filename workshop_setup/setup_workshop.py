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
from datetime import timedelta
from pathlib import Path

try:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.common.lro import LroOptions
    from databricks.sdk.errors import AlreadyExists, ResourceAlreadyExists
    from databricks.sdk.service import iam, postgres
    from databricks.sdk.service.catalog import PermissionsChange, Privilege, VolumeType
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

    while True:
        try:
            choice = input(f"\nSelect profile [1-{len(profiles)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(profiles):
                return profiles[idx]
            print(f"Please enter a number between 1 and {len(profiles)}")
        except ValueError:
            print(f"Please enter a number between 1 and {len(profiles)}")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(1)


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


def create_lakebase(w: WorkspaceClient, display_name: str, pg_version: int = 17) -> None:
    project_id = _to_project_id(display_name)
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
        _grant_lakebase_project_manage_all_account_users(w, project_id)
        return
    except Exception as e:
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


# ---------------------------------------------------------------------------
# Unity Catalog (catalog, schemas, volume referenced by the backend)
# ---------------------------------------------------------------------------

def _is_already_exists(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("already exists", "conflict", "409"))


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
) -> None:
    """Create the catalog, bronze/silver/volume schemas, the managed volume the
    backend uses, grant read access on the catalog to all account users, and
    grant MANAGE on the volume to all account users."""
    print(f"\nCreating Unity Catalog resources (catalog: {catalog_name})...")

    # Catalog. Workspaces without a metastore storage root require an explicit
    # MANAGED LOCATION; fall back to the first external location's URL.
    storage_root = _first_external_location_url(w)
    try:
        w.catalogs.create(name=catalog_name, storage_root=storage_root)
        loc_note = f" (storage_root={storage_root})" if storage_root else ""
        print(f"  [+] catalog '{catalog_name}'{loc_note}")
    except (AlreadyExists, ResourceAlreadyExists):
        print(f"  [~] catalog '{catalog_name}' (already exists)")
    except Exception as e:
        if _is_already_exists(e):
            print(f"  [~] catalog '{catalog_name}' (already exists)")
        else:
            print(f"  [!] catalog '{catalog_name}' — {e}")
            sys.exit(1)

    # Schemas (bronze + silver + the schema that holds the volume; UC auto-creates
    # 'default' but we attempt it idempotently in case the catalog was created without one)
    for schema in {bronze_schema, silver_schema, volume_schema}:
        try:
            w.schemas.create(name=schema, catalog_name=catalog_name)
            print(f"  [+] schema '{catalog_name}.{schema}'")
        except (AlreadyExists, ResourceAlreadyExists):
            print(f"  [~] schema '{catalog_name}.{schema}' (already exists)")
        except Exception as e:
            if _is_already_exists(e):
                print(f"  [~] schema '{catalog_name}.{schema}' (already exists)")
            else:
                print(f"  [!] schema '{catalog_name}.{schema}' — {e}")
                sys.exit(1)

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
    try:
        w.volumes.create(
            catalog_name=catalog_name,
            schema_name=volume_schema,
            name=volume_name,
            volume_type=VolumeType.MANAGED,
        )
        print(f"  [+] volume '{full_volume}'")
    except (AlreadyExists, ResourceAlreadyExists):
        print(f"  [~] volume '{full_volume}' (already exists)")
    except Exception as e:
        if _is_already_exists(e):
            print(f"  [~] volume '{full_volume}' (already exists)")
        else:
            print(f"  [!] volume '{full_volume}' — {e}")
            sys.exit(1)

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
        except (AlreadyExists, ResourceAlreadyExists):
            print(f"  [~] {email} (already exists)")
            skipped += 1
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ("already exists", "conflict", "409", "uniqueness")):
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

    if args.users_only:
        provision_users(w, args.users_file)
    elif args.lakebase_only:
        create_lakebase(w, args.lakebase_name, args.pg_version)
    elif args.uc_only:
        create_uc_resources(w, args.catalog)
    else:
        create_lakebase(w, args.lakebase_name, args.pg_version)
        create_uc_resources(w, args.catalog)
        provision_users(w, args.users_file)

    print("\nWorkshop setup complete.")


if __name__ == "__main__":
    main()
