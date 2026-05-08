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
except ImportError:
    print("Error: databricks-sdk is required.  pip install databricks-sdk")
    sys.exit(1)


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
    except Exception as e:
        print(f"\n  Operation ended: {e}")


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
  # Full setup — Lakebase + users:
  python setup_workshop.py --users-file participants.txt

  # Lakebase only:
  python setup_workshop.py --lakebase-only

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
        default="Disaster Recovery Tracker",
        metavar="NAME",
        help="Lakebase display name (default: Disaster Recovery Tracker)",
    )
    parser.add_argument(
        "--pg-version",
        type=int,
        default=17,
        choices=[16, 17],
        metavar="VER",
        help="PostgreSQL major version (16 or 17, default: 17)",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--lakebase-only",
        action="store_true",
        help="Only create the Lakebase project, skip user provisioning",
    )
    mode.add_argument(
        "--users-only",
        action="store_true",
        help="Only provision users, skip Lakebase creation",
    )

    args = parser.parse_args()

    if not args.lakebase_only and not args.users_file:
        parser.error("--users-file is required unless --lakebase-only is specified")

    profiles = get_profiles()
    profile = select_profile(profiles, args.profile)
    print(f"Profile: {profile}")

    w = WorkspaceClient(profile=profile)

    if args.users_only:
        provision_users(w, args.users_file)
    elif args.lakebase_only:
        create_lakebase(w, args.lakebase_name, args.pg_version)
    else:
        create_lakebase(w, args.lakebase_name, args.pg_version)
        provision_users(w, args.users_file)

    print("\nWorkshop setup complete.")


if __name__ == "__main__":
    main()
