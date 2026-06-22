#!/usr/bin/env python3
"""Workshop setup script for the Disaster Recovery Tracker lab.

Creates an autoscaling Lakebase (Postgres) project, Unity Catalog resources, and
provisions workspace users. By default also provisions an S3 bucket (us-west-2),
IAM role, storage credential, and external location for the FEMA catalog (requires
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN).

The Databricks CLI profile from ~/.databrickscfg can be passed with --profile/-p
(e.g. --profile fema); if omitted, you are prompted to choose one.

Requires: databricks-sdk, boto3  (pip install -r requirements.txt)
"""

import argparse
import configparser
import json
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import TypedDict

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc, assignment]

try:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.common.lro import LroOptions
    from databricks.sdk.errors import AlreadyExists, NotFound, ResourceAlreadyExists
    from databricks.sdk.service import iam, postgres
    from databricks.sdk.service.catalog import (
        AwsIamRoleRequest,
        PermissionsChange,
        Privilege,
        VolumeType,
    )
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

# Unity Catalog on AWS: Databricks master role that assumes customer IAM roles.
UC_AWS_MASTER_ROLE_ARN = (
    "arn:aws:iam::414351767826:role/unity-catalog-prod-UCMasterRole-14S5ZJVKOTYTL"
)
AWS_UC_REGION = "us-west-2"
UC_PLACEHOLDER_EXTERNAL_ID = "0000"

# Built-in account group (Unity Catalog principal and Permissions API ``group_name``;
# UI label: All account users).
ALL_USERS_PRINCIPAL = "account users"

# Workspace entitlements each workshop participant needs: access to the
# workspace itself and to Databricks SQL (warehouses/dashboards/queries).
WORKSHOP_ENTITLEMENTS = ("workspace-access", "databricks-sql-access")

# Seconds to wait after creating a new IAM role before updating its trust policy.
IAM_ROLE_PROPAGATION_SECONDS = 10

# Terminal states for SQL statement execution polling.
_SQL_TERMINAL_STATES = frozenset({
    StatementState.SUCCEEDED,
    StatementState.FAILED,
    StatementState.CANCELED,
    StatementState.CLOSED,
})


class AwsUcStorage(TypedDict):
    external_location_url: str
    managed_location: str
    storage_credential_name: str
    external_location_name: str


# ---------------------------------------------------------------------------
# Shared helpers
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


def _grant_privileges(
    w: WorkspaceClient,
    *,
    securable_type: str,
    full_name: str,
    privileges: list[Privilege],
    description: str,
) -> None:
    try:
        w.grants.update(
            securable_type=securable_type,
            full_name=full_name,
            changes=[
                PermissionsChange(
                    principal=ALL_USERS_PRINCIPAL,
                    add=privileges,
                )
            ],
        )
        privs = ", ".join(p.value for p in privileges)
        print(f"  [+] grants on {description} '{full_name}' to '{ALL_USERS_PRINCIPAL}': {privs}")
    except Exception as e:
        print(f"  [!] grant on {description} '{full_name}' — {e}")
        sys.exit(1)


def _normalize_storage_url(url: str) -> str:
    return url.rstrip("/") + "/"


def _client_error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "")


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


def _account_users_can_manage_lakebase(w: WorkspaceClient, project_id: str) -> bool:
    """Return True if the All-account-users group already has CAN_MANAGE on the project."""
    perms = w.permissions.get(
        request_object_type="database-projects",
        request_object_id=project_id,
    )
    for ace in perms.access_control_list or []:
        if ace.group_name != ALL_USERS_PRINCIPAL:
            continue
        levels = {p.permission_level for p in (ace.all_permissions or [])}
        if iam.PermissionLevel.CAN_MANAGE in levels:
            return True
    return False


def verify_lakebase_project_permission(w: WorkspaceClient, display_name: str) -> None:
    """Ensure the Lakebase project CAN_MANAGE grant for All account users is in place.

    Safe to call on re-runs: reads the current ACL and only (re)grants if the
    group's CAN_MANAGE permission is missing.
    """
    project_id = _to_project_id(display_name)
    try:
        if not _lakebase_project_exists(w, project_id):
            print(
                f"  [!] Lakebase project '{project_id}' not found — skipping permission check"
            )
            return
        if _account_users_can_manage_lakebase(w, project_id):
            print(
                f"  [~] Lakebase project '{project_id}': CAN_MANAGE for "
                f"'{ALL_USERS_PRINCIPAL}' already granted"
            )
            return
    except Exception as e:
        print(f"  [!] could not verify Lakebase project permissions on '{project_id}' — {e}")
        return
    _grant_lakebase_project_manage_all_account_users(w, project_id)


def _lakebase_on_already_exists(
    w: WorkspaceClient, project_id: str, *, skip_if_exists: bool
) -> None:
    print(f"  Lakebase project '{project_id}' already exists, skipping.")
    if not skip_if_exists:
        _grant_lakebase_project_manage_all_account_users(w, project_id)


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
        _lakebase_on_already_exists(w, project_id, skip_if_exists=skip_if_exists)
        return
    except Exception as e:
        if _is_already_exists(e):
            _lakebase_on_already_exists(w, project_id, skip_if_exists=skip_if_exists)
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
    while resp.status and resp.status.state not in _SQL_TERMINAL_STATES:
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


_AWS_ENV_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)


def _require_aws_credentials() -> None:
    """Exit with setup instructions when AWS env vars are missing."""
    missing = [name for name in _AWS_ENV_VARS if not os.environ.get(name)]
    if not missing:
        return
    print("Error: AWS environment variables are required for Unity Catalog storage setup.")
    print("Set the following in your shell, then re-run this script:\n")
    for name in _AWS_ENV_VARS:
        marker = "  (missing)" if name in missing else ""
        print(f"  export {name}=<value>{marker}")
    sys.exit(1)


def _require_boto3() -> None:
    if boto3 is None:
        print("Error: boto3 is required for AWS provisioning.  pip install boto3")
        sys.exit(1)


def _aws_session_from_env() -> "boto3.Session":
    """Build a boto3 session from AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN."""
    _require_boto3()
    _require_aws_credentials()
    return boto3.Session(
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        aws_session_token=os.environ["AWS_SESSION_TOKEN"],
        region_name=AWS_UC_REGION,
    )


def _catalog_managed_location(external_location_url: str, catalog_name: str) -> str:
    """Managed location for a catalog; must be under the external location prefix."""
    return _normalize_storage_url(f"{external_location_url.rstrip('/')}/{catalog_name}")


def _aws_uc_resource_names(catalog_name: str, aws_account_id: str) -> dict[str, str]:
    safe = re.sub(r"[^a-z0-9-]", "-", catalog_name.lower()).strip("-") or "fema"
    bucket = f"databricks-{safe}-uc-{aws_account_id}"[:63].rstrip("-")
    role_name = f"{safe}-unity-catalog-storage"[:64]
    return {
        "bucket_name": bucket,
        "role_name": role_name,
        "role_arn": f"arn:aws:iam::{aws_account_id}:role/{role_name}",
        "storage_credential_name": f"{safe}-storage-credential",
        "external_location_name": f"{safe}-external-location",
    }


def _iam_trust_policy(
    external_id: str,
    *,
    role_arn: str | None = None,
    self_assume_via_root: bool = False,
) -> str:
    """Build IAM trust policy for Unity Catalog storage credentials.

    New roles start with UC master only (role_arn=None). After the storage
    credential exists, add self-assume in a separate statement — AWS rejects
    mixing cross-account and same-account principals in one statement.
    """
    external_id = str(external_id).strip()
    statements: list[dict] = [
        {
            "Sid": "UnityCatalogMasterAssume",
            "Effect": "Allow",
            "Principal": {"AWS": UC_AWS_MASTER_ROLE_ARN},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"sts:ExternalId": external_id}},
        },
    ]
    if role_arn:
        if self_assume_via_root:
            account_id = role_arn.split(":")[4]
            principal: dict[str, str] = {"AWS": f"arn:aws:iam::{account_id}:root"}
            extra_condition = {"ArnLike": {"aws:PrincipalArn": role_arn}}
        else:
            principal = {"AWS": role_arn}
            extra_condition = {}
        self_statement: dict = {
            "Sid": "RoleSelfAssume",
            "Effect": "Allow",
            "Principal": principal,
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"sts:ExternalId": external_id}, **extra_condition},
        }
        statements.append(self_statement)
    return json.dumps({"Version": "2012-10-17", "Statement": statements})


def _get_iam_role_arn(iam_client, role_name: str) -> str:
    return iam_client.get_role(RoleName=role_name)["Role"]["Arn"]


def _iam_s3_access_policy(bucket_name: str, aws_account_id: str, role_name: str) -> str:
    bucket_arn = f"arn:aws:s3:::{bucket_name}"
    role_arn = f"arn:aws:iam::{aws_account_id}:role/{role_name}"
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:DeleteObject",
                        "s3:ListBucket",
                        "s3:GetBucketLocation",
                        "s3:ListBucketMultipartUploads",
                        "s3:ListMultipartUploadParts",
                        "s3:AbortMultipartUpload",
                    ],
                    "Resource": [bucket_arn, f"{bucket_arn}/*"],
                },
                {
                    "Effect": "Allow",
                    "Action": "sts:AssumeRole",
                    "Resource": role_arn,
                },
            ],
        }
    )


def _ensure_s3_bucket(s3_client, bucket_name: str) -> None:
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"  [~] S3 bucket '{bucket_name}' (already exists)")
    except ClientError as e:
        if _client_error_code(e) not in ("404", "NoSuchBucket", "NotFound"):
            raise
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": AWS_UC_REGION},
        )
        print(f"  [+] S3 bucket '{bucket_name}' ({AWS_UC_REGION})")


def _ensure_iam_role(iam_client, role_name: str) -> None:
    try:
        iam_client.get_role(RoleName=role_name)
        print(f"  [~] IAM role '{role_name}' (already exists)")
    except ClientError as e:
        if _client_error_code(e) != "NoSuchEntity":
            raise
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=_iam_trust_policy(UC_PLACEHOLDER_EXTERNAL_ID),
            Description="Unity Catalog storage access for workshop setup",
        )
        print(f"  [+] IAM role '{role_name}'")
        time.sleep(IAM_ROLE_PROPAGATION_SECONDS)


def _ensure_iam_role_policy(
    iam_client, policy_name: str, role_name: str, policy_document: str
) -> None:
    try:
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=policy_document,
        )
        print(f"  [+] IAM inline policy '{policy_name}' on '{role_name}'")
    except ClientError as e:
        print(f"  [!] IAM policy '{policy_name}' on '{role_name}' — {e}")
        sys.exit(1)


def _update_iam_trust_external_id(
    iam_client, role_name: str, external_id: str
) -> None:
    role_arn = _get_iam_role_arn(iam_client, role_name)
    policy_variants = (
        ("role principal", False),
        ("account root + ArnLike", True),
    )
    last_error: ClientError | None = None
    for label, use_root in policy_variants:
        policy = _iam_trust_policy(
            external_id, role_arn=role_arn, self_assume_via_root=use_root
        )
        try:
            iam_client.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=policy,
            )
            print(
                f"  [+] IAM trust policy on '{role_name}' "
                f"(self-assume + external ID, {label})"
            )
            return
        except ClientError as e:
            if _client_error_code(e) != "MalformedPolicyDocument":
                raise
            last_error = e
            print(f"  [~] trust policy variant ({label}) rejected, trying next...")
    print(
        f"  [!] IAM trust policy update failed for '{role_name}' (role_arn={role_arn})."
    )
    print(
        "  [!] Update the trust policy manually in AWS: add the storage credential "
        "external ID and allow the role to assume itself (see Databricks S3 UC docs)."
    )
    if last_error:
        raise last_error


def _storage_credential_external_id(cred) -> str | None:
    if cred.aws_iam_role and cred.aws_iam_role.external_id:
        return cred.aws_iam_role.external_id
    return None


def _get_storage_credential_external_id(w: WorkspaceClient, credential_name: str) -> str | None:
    try:
        cred = w.storage_credentials.get(name=credential_name)
    except NotFound:
        return None
    return _storage_credential_external_id(cred)


def _get_or_create_storage_credential(
    w: WorkspaceClient, credential_name: str, role_arn: str
) -> str:
    external_id = _get_storage_credential_external_id(w, credential_name)
    if external_id:
        print(f"  [~] storage credential '{credential_name}' (already exists)")
        return external_id

    w.storage_credentials.create(
        name=credential_name,
        aws_iam_role=AwsIamRoleRequest(role_arn=role_arn),
        comment="Workshop setup (disaster-recovery-tracker)",
        skip_validation=True,
    )
    external_id = _get_storage_credential_external_id(w, credential_name)
    if not external_id:
        print(f"  [!] storage credential '{credential_name}' — no external ID returned")
        sys.exit(1)
    print(f"  [+] storage credential '{credential_name}'")
    return external_id


def _validate_storage_credential(
    w: WorkspaceClient,
    credential_name: str,
    location_url: str,
    *,
    external_location_name: str | None = None,
) -> None:
    try:
        w.storage_credentials.validate(
            storage_credential_name=credential_name,
            url=location_url,
            external_location_name=external_location_name,
        )
        print(f"  [+] validated storage credential '{credential_name}'")
    except Exception as e:
        print(f"  [!] storage credential validation — {e}")
        sys.exit(1)


def _get_or_create_external_location(
    w: WorkspaceClient,
    location_name: str,
    location_url: str,
    credential_name: str,
) -> str:
    try:
        loc = w.external_locations.get(name=location_name)
        if loc.url:
            print(f"  [~] external location '{location_name}' (already exists)")
            return loc.url
    except NotFound:
        pass

    loc = w.external_locations.create(
        name=location_name,
        url=location_url,
        credential_name=credential_name,
        comment="Workshop setup (disaster-recovery-tracker)",
        skip_validation=True,
    )
    url = loc.url or location_url
    print(f"  [+] external location '{location_name}' ({url})")
    return url


def provision_aws_uc_storage_for_catalog(
    w: WorkspaceClient, catalog_name: str
) -> AwsUcStorage:
    """Create S3 bucket, IAM role, UC storage credential, and external location.

    Uses AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_SESSION_TOKEN from the
    environment. Returns URLs and UC object names for catalog/volume setup.
    """
    print(f"\nProvisioning AWS storage for Unity Catalog (catalog: {catalog_name})...")
    session = _aws_session_from_env()
    sts = session.client("sts")
    aws_account_id = sts.get_caller_identity()["Account"]
    names = _aws_uc_resource_names(catalog_name, aws_account_id)
    location_url = _normalize_storage_url(f"s3://{names['bucket_name']}")

    s3 = session.client("s3")
    iam = session.client("iam")

    _ensure_s3_bucket(s3, names["bucket_name"])
    _ensure_iam_role(iam, names["role_name"])
    _ensure_iam_role_policy(
        iam,
        policy_name=f"{names['role_name']}-s3-access",
        role_name=names["role_name"],
        policy_document=_iam_s3_access_policy(
            names["bucket_name"], aws_account_id, names["role_name"]
        ),
    )

    external_id = _get_or_create_storage_credential(
        w, names["storage_credential_name"], names["role_arn"]
    )
    _update_iam_trust_external_id(iam, names["role_name"], external_id)

    url = _get_or_create_external_location(
        w,
        names["external_location_name"],
        location_url,
        names["storage_credential_name"],
    )
    managed_location = _catalog_managed_location(url, catalog_name)
    _validate_storage_credential(
        w,
        names["storage_credential_name"],
        managed_location,
        external_location_name=names["external_location_name"],
    )
    return {
        "external_location_url": url,
        "managed_location": managed_location,
        "storage_credential_name": names["storage_credential_name"],
        "external_location_name": names["external_location_name"],
    }


def _get_catalog_storage_root(w: WorkspaceClient, catalog_name: str) -> str | None:
    try:
        catalog = w.catalogs.get(name=catalog_name)
    except NotFound:
        return None
    for attr in ("storage_root", "storage_location"):
        value = getattr(catalog, attr, None)
        if value:
            return value
    return None


def _alter_catalog_managed_location_sql(
    w: WorkspaceClient,
    catalog_name: str,
    managed_location: str,
    warehouse_id: str | None,
) -> None:
    safe_name = _sql_identifier(catalog_name, label="catalog name")
    escaped_location = managed_location.replace("'", "''")
    statement = (
        f"ALTER CATALOG {safe_name} SET MANAGED LOCATION '{escaped_location}'"
    )
    _execute_sql_statement(w, _resolve_sql_warehouse_id(w, warehouse_id), statement)


def _ensure_catalog_managed_location(
    w: WorkspaceClient,
    catalog_name: str,
    managed_location: str,
    warehouse_id: str | None,
) -> None:
    """Create the catalog or point an existing catalog at the S3 managed location."""
    managed_location = _normalize_storage_url(managed_location)
    current = _get_catalog_storage_root(w, catalog_name)
    if current:
        if _normalize_storage_url(current) == managed_location:
            print(
                f"  [~] catalog '{catalog_name}' managed location "
                f"({managed_location})"
            )
            return
        print(
            f"  [*] Updating catalog '{catalog_name}' managed location:\n"
            f"      was: {current}\n"
            f"      now: {managed_location}"
        )
        _alter_catalog_managed_location_sql(
            w, catalog_name, managed_location, warehouse_id
        )
        print(f"  [+] catalog '{catalog_name}' managed location updated")
        return

    _create_idempotent(
        lambda: w.catalogs.create(name=catalog_name, storage_root=managed_location),
        created_msg=f"catalog '{catalog_name}' (storage_root={managed_location})",
        exists_msg=f"catalog '{catalog_name}' (already exists)",
        error_label=f"catalog '{catalog_name}'",
    )
    # Catalog may have been created concurrently; ensure managed location is set.
    if not _get_catalog_storage_root(w, catalog_name):
        _alter_catalog_managed_location_sql(
            w, catalog_name, managed_location, warehouse_id
        )
        print(f"  [+] catalog '{catalog_name}' managed location set")


def _grant_aws_uc_storage_access(
    w: WorkspaceClient,
    storage_credential_name: str,
    external_location_name: str,
) -> None:
    """Grant account users access for managed-catalog storage (not external volumes)."""
    _grant_privileges(
        w,
        securable_type="storage_credential",
        full_name=storage_credential_name,
        privileges=[
            Privilege.CREATE_EXTERNAL_TABLE,
            Privilege.READ_FILES,
            Privilege.WRITE_FILES,
        ],
        description="storage credential",
    )
    _grant_privileges(
        w,
        securable_type="external_location",
        full_name=external_location_name,
        privileges=[Privilege.READ_FILES, Privilege.WRITE_FILES],
        description="external location",
    )


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
    provision_aws_storage: bool = True,
) -> None:
    """Create the catalog, bronze/silver/volume schemas, the managed volume the
    backend uses, grant read access on the catalog to all account users, and
    grant READ_VOLUME, WRITE_VOLUME, and MANAGE on the volume to all account users."""
    print(f"\nCreating Unity Catalog resources (catalog: {catalog_name})...")

    # Catalog MANAGED LOCATION: S3 + storage credential + external location.
    # Use --skip-aws-provisioning to fall back without AWS env vars.
    aws_storage: AwsUcStorage | None = None
    if provision_aws_storage:
        _require_aws_credentials()
        aws_storage = provision_aws_uc_storage_for_catalog(w, catalog_name)
        _grant_aws_uc_storage_access(
            w,
            aws_storage["storage_credential_name"],
            aws_storage["external_location_name"],
        )
        _ensure_catalog_managed_location(
            w,
            catalog_name,
            aws_storage["managed_location"],
            warehouse_id,
        )
    else:
        storage_root = _first_external_location_url(w)
        if storage_root:
            _create_idempotent(
                lambda: w.catalogs.create(
                    name=catalog_name, storage_root=storage_root
                ),
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

    _grant_privileges(
        w,
        securable_type="catalog",
        full_name=catalog_name,
        privileges=[Privilege.USE_CATALOG, Privilege.USE_SCHEMA, Privilege.SELECT],
        description=f"catalog '{catalog_name}'",
    )

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
    _grant_privileges(
        w,
        securable_type="volume",
        full_name=volume_securable_name,
        privileges=[Privilege.READ_VOLUME, Privilege.WRITE_VOLUME, Privilege.MANAGE],
        description=f"volume '{volume_securable_name}'",
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _entitlement_values() -> list[iam.ComplexValue]:
    return [iam.ComplexValue(value=e) for e in WORKSHOP_ENTITLEMENTS]


def _find_user(w: WorkspaceClient, email: str) -> iam.User | None:
    """Return the existing workspace user with this user_name, or None.

    list() responses often omit the ``entitlements`` attribute, so re-fetch the
    full resource with get() to get an authoritative entitlement list.
    """
    escaped = email.replace('"', '\\"')
    match = next(iter(w.users.list(filter=f'userName eq "{escaped}"')), None)
    if match is None or not match.id:
        return None
    return w.users.get(id=match.id)


def _ensure_entitlements(w: WorkspaceClient, user: iam.User) -> int:
    """Grant any workshop entitlements the user is missing. Returns count added."""
    current = {e.value for e in (user.entitlements or []) if e.value}
    missing = [e for e in WORKSHOP_ENTITLEMENTS if e not in current]
    if not missing:
        return 0

    operations = [
        iam.Patch(
            op=iam.PatchOp.ADD,
            path="entitlements",
            value=[{"value": e} for e in missing],
        )
    ]
    w.users.patch(
        id=user.id,
        operations=operations,
        schemas=[iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP],
    )
    print(f"      + entitlements: {', '.join(missing)}")
    return len(missing)


def provision_users(
    w: WorkspaceClient,
    users_file: str,
    lakebase_name: str | None = None,
    *,
    verify_lakebase_permission: bool = False,
) -> None:
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

    success = skipped = failed = warnings = 0
    for email in emails:
        display = email.split("@")[0]
        try:
            w.users.create(
                user_name=email,
                display_name=display,
                active=True,
                emails=[iam.ComplexValue(value=email, primary=True)],
                entitlements=_entitlement_values(),
            )
            print(f"  [+] {email}")
            success += 1
        except Exception as e:
            if not _is_already_exists(e):
                print(f"  [!] {email} — {e}")
                failed += 1
                continue
            # User already exists — still verify the workshop entitlements are
            # granted, since a pre-existing user may predate this setup.
            print(f"  [~] {email} (already exists)")
            skipped += 1
            try:
                existing = _find_user(w, email)
                if existing is None:
                    print(f"      [!] could not look up '{email}' to check entitlements")
                    warnings += 1
                elif _ensure_entitlements(w, existing) == 0:
                    print("      entitlements already granted")
            except Exception as ee:
                print(f"      [!] entitlement check for '{email}' — {ee}")
                warnings += 1

    summary = f"\n  Users: {success} created, {skipped} already existed, {failed} failed."
    if warnings:
        summary += f" ({warnings} entitlement warning(s) — see above.)"
    print(summary)

    # Participants reach Lakebase through the All-account-users group grant, so
    # confirm that project permission is in place even when every user already
    # existed (e.g. a --users-only re-run after the project was recreated).
    if lakebase_name and verify_lakebase_permission:
        print("\nVerifying Lakebase project permission for All account users...")
        verify_lakebase_project_permission(w, lakebase_name)


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

  # UC setup with AWS creds (S3 bucket + IAM role + storage credential + external location):
  export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...
  python setup_workshop.py --uc-only --profile vm-fema-1
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
            "updates, including the --users-only verification pass "
            "(default: still apply CAN_MANAGE for All account users)"
        ),
    )
    parser.add_argument(
        "--skip-aws-provisioning",
        action="store_true",
        help=(
            "Skip S3/IAM/UC provisioning (no AWS env vars required); use an existing "
            "external location or CREATE CATALOG IF NOT EXISTS instead"
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
    uc_kwargs = {
        "warehouse_id": args.warehouse_id,
        "provision_aws_storage": not args.skip_aws_provisioning,
    }

    if args.users_only:
        # No Lakebase project is created in this run, so verifying its group
        # permission here is the only way to ensure participants can reach it
        # (unless the user opted out of Lakebase permission updates).
        provision_users(
            w,
            args.users_file,
            args.lakebase_name,
            verify_lakebase_permission=not args.skip_lakebase_if_exists,
        )
    elif args.lakebase_only:
        create_lakebase(w, args.lakebase_name, args.pg_version, **lakebase_kwargs)
    elif args.uc_only:
        create_uc_resources(w, args.catalog, **uc_kwargs)
    else:
        # create_lakebase already ensures the group permission, so no separate
        # verification pass is needed during user provisioning here.
        create_lakebase(w, args.lakebase_name, args.pg_version, **lakebase_kwargs)
        create_uc_resources(w, args.catalog, **uc_kwargs)
        provision_users(w, args.users_file, args.lakebase_name)

    print("\nWorkshop setup complete.")


if __name__ == "__main__":
    main()
