# Lab 1.1: Environment Variables and App Resources

**Goal:** This lab walks you through how the Disaster Recovery Tracker gets its SQL warehouse, Lakebase database, and credentials at runtime — using environment variables that Databricks Apps injects when you connect resources, so nothing secret has to live in the Git repository.

**Docs:** [Define environment variables in a Databricks app](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/environment-variables)

---

## Before you start

- You completed **Lab 1**, so the Databricks App `fema-claims-tracker-<your name>` is deployed and running.
- You connected a **Lakebase** database, a **SQL warehouse**, and a **Unity Catalog Volume** when you created the app.

---

## Part A — Open the app resources you connected in Lab 1

When you deployed the app you granted it access to three resources. Those connections are more than a configuration list: Databricks also grants the app's **service principal (SP)** permission on each resource, then injects identifiers and connection details into the running process as environment variables.

1. From the top right view switcher, click **Databricks Apps** and open your **`fema-claims-tracker-<your name>`** app.
2. From the vertical left menu click **Settings**, then go to the **Resources** section.
3. Confirm you still see the three resources from Lab 1:
   - **Lakebase** — the OLTP database (system of record for claims).
   - **SQL warehouse** — used for analytics SQL such as `ai_parse_document` / `ai_extract`.
   - **UC Volume** — the filestore for images and PDFs.

Note the **resource key** on the SQL warehouse (the default is `sql-warehouse`). That key is how `app.yaml` refers to the warehouse without hardcoding a warehouse ID.

> **Behind the scenes:** The same source code can be deployed by every student. Each warehouse and database value in the App resources screen is resolved at deploy time. You do not change Python to point at a different warehouse when the app is deloyed in a different workspace ie dev, test or prod.

---

## Part B — Trace the SQL warehouse into `WAREHOUSE_ID`

1. In the workshop repository, open `app.yaml`.
2. Find this block in the `env` section:

    ```yaml
    - name: WAREHOUSE_ID
      valueFrom: sql-warehouse
    ```

3. Compare that to what you saw in **Resources**:
   - `WAREHOUSE_ID` is the environment variable the Python process reads.
   - `sql-warehouse` is the resource key (not a warehouse ID you typed by hand).
   - `valueFrom` tells Databricks to fill the variable from the connected resource at runtime.

4. Open `backend/config.py` and find:

    ```python
    WAREHOUSE_ID = (os.getenv("WAREHOUSE_ID") or "").strip()
    ```

5. Open `backend/document_ai_sql.py` and notice it uses `WAREHOUSE_ID` when it calls the **Statement Execution API**. That is how document extraction in the next lab knows *which warehouse* to run `ai_parse_document` and `ai_extract` on.

The warehouse ID is an identifier, not a password. Authentication for those SQL calls comes from the app's service principal — you will see that in Part D.

---

## Part C — See how the app connects to Postgres (Lakebase)

1. Still in `app.yaml`, find the Lakebase resource:

    ```yaml
    resources:
      - name: disaster-recovery-lakebase
        type: postgres
        project: disaster-recovery-tracker
        branch: production
        endpoint: primary
    ```

2. Back in the app **Resources** page, confirm the Lakebase resource matches that project / `production` branch.

For the first attached Postgres resource, Databricks Apps automatically injects the usual PostgreSQL connection variables. You do **not** have to list them all in `app.yaml`:

| Variable | What it is |
|----------|------------|
| `PGHOST` | Hostname of the Lakebase Postgres endpoint |
| `PGPORT` | Postgres port |
| `PGDATABASE` | Database name (typically `databricks_postgres`) |
| `PGUSER` | The app service principal's Postgres role |
| `PGSSLMODE` | SSL mode (`require`) |
| `PGAPPNAME` | The app name |

3. Open `backend/config.py` and find where those values are read:

    ```python
    PGUSER = os.getenv("PGUSER", "")
    PGHOST = os.getenv("PGHOST", "")
    PGPORT = os.getenv("PGPORT", "5432")
    PGDATABASE = os.getenv("PGDATABASE", "databricks_postgres")
    PGSSLMODE = os.getenv("PGSSLMODE", "require")
    ```

4. Open `backend/main.py` and find `_build_conninfo()`. It stitches those variables into a Postgres connection string:

    ```python
    return f"dbname={PGDATABASE} user={user} host={host} port={PGPORT} sslmode={PGSSLMODE}"
    ```

On Databricks Apps, `PGHOST` and `PGUSER` are already set, so the app does not need a hostname copied into source control for each student's deployment.

> **Do not dump the process environment or log secrets.** Variables such as `DATABRICKS_CLIENT_SECRET` and short-lived database tokens must never be pasted into chat, slides, or screenshots.

---

## Part D — Credentials are injected the same way

Connection variables answer **where** to connect. Credentials prove **who** the app is.

Every Databricks App gets a dedicated **service principal**. Databricks injects OAuth values into the runtime automatically (you do not put them in `app.yaml`):

- `DATABRICKS_HOST`
- `DATABRICKS_CLIENT_ID`
- `DATABRICKS_CLIENT_SECRET`

1. Open `backend/databricks_auth.py` and find:

    ```python
    w = WorkspaceClient()
    ```

    No client ID or secret is passed in. The Databricks SDK uses [unified authentication](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/auth) and picks up the injected variables. The client acts as the **app**, not as the person who opened the browser.

2. The same `WorkspaceClient` is used in two places:
   - **SQL warehouse:** statement execution runs as the app SP against the warehouse in `WAREHOUSE_ID`.
   - **Lakebase:** the app exchanges that identity for a short-lived database credential.

3. In `backend/main.py`, find the `OAuthConnection` class:

    ```python
    cred = w.postgres.generate_database_credential(
        endpoint=_resolve_lakebase_endpoint()
    )
    kwargs["password"] = cred.token
    ```

    That token is the PostgreSQL password for the connection. It is created at runtime, never committed to Git, and never stored in `app.yaml`. The connection pool recycles connections before the token expires so the next connect gets a fresh one.

This is why Lab 1 asked you to grant the app SP database permissions. Injecting credentials **authenticates** the app; the role you granted **authorizes** it to read and write tables.

> **⚠ Not a production pattern reminder.** Lab 1 used `databricks_superuser` to keep the workshop moving. A real app would use a narrower Postgres role. The injection mechanism is the same either way.

---

## Part E — `value` vs `valueFrom`

Look at these two entries in `app.yaml` side by side:

```yaml
- name: LLM_ENDPOINT
  value: "databricks-llama-4-maverick"
- name: WAREHOUSE_ID
  valueFrom: sql-warehouse
```

- Use **`value`** for static, non-sensitive settings that should be the same for every deployment (model names, feature flags, timezones).
- Use **`valueFrom`** for managed resources and secrets. Databricks fills them from the resource you attached — so warehouse IDs, volume paths, and secret values stay out of the repo.

The Volume path follows the same pattern:

```yaml
- name: VOLUME_PATH
  valueFrom: volume
```

That resolves to the governed `/Volumes/<catalog>/<schema>/<volume>` path you selected in Lab 1 — which is where claim files land in the next lab.

### Why this matters

- **No extra secret store in the app.** Warehouse IDs, Postgres host, and OAuth client secrets arrive as environment variables. The repo stays portable.
- **Resources carry permissions.** Connecting a warehouse or database in the UI both *points* the app at that resource and *grants* the SP access to it.
- **Same pattern for files.** `VOLUME_PATH` is how Unity Catalog Volumes become the app's filesystem without another product.

---

## Congratulations — you now know how the app finds its warehouse, database, and credentials!

In the next lab you will submit a claim. When the app runs `ai_extract` on a PDF, it is using the `WAREHOUSE_ID` you just traced; when it saves the claim row, it is using the injected `PGHOST` / `PGUSER` plus a short-lived Lakebase token.

## Need help?

- **`WAREHOUSE_ID` looks empty / document AI fails later:** Open the app **Resources** tab and confirm a SQL warehouse is attached with the key `sql-warehouse`, then **Deploy** again.
- **App can't connect to Postgres:** Confirm the Lakebase resource is still on the `Disaster Recovery Tracker` project and `production` branch, and that you granted the app SP `databricks_superuser` in Lab 1.
- **You changed a resource but nothing changed:** Resource bindings are applied at **deploy** time. Click **Deploy** after editing Resources.
