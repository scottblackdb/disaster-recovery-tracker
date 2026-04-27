# Lab 2 (Instructor Only): Sync Lakebase to the Lakehouse

> **Audience:** Instructor only. Students should **not** run these steps. The output of this lab — synced tables in Unity Catalog — is what the students will query from the AI/BI dashboard in the next lab.

**Goal:** Create **Lakebase synced tables** that continuously replicate the Disaster Recovery Tracker's OLTP data from **Lakebase (Postgres)** into the **Lakehouse (Unity Catalog Delta tables)** so the data is available for analytics and the AI/BI dashboard.

**Source (Lakebase / Postgres):** `fema-disaster-recovery` Lakebase instance, `public` schema.

**Destination (Lakehouse / Unity Catalog):** `fema_claims_workshop_catalog.public.*`

---

## Before you start

- You must be a **workspace admin** or have permission to create synced tables and write to `fema_claims_workshop_catalog`.
- The Databricks App from **Lab 1** must already be deployed and have written at least one row into Lakebase (so the source tables exist and have data).
- Confirm the Lakebase instance **`fema-disaster-recovery`** is running and reachable from the workspace.

---

## Part A — Confirm the source tables in Lakebase

1. In the workspace left nav, open **Compute → Database instances**.
2. Click the **`fema-disaster-recovery`** Lakebase instance.
3. Open the **Databases** tab and expand the `databricks_postgres` database (or whichever database the app writes to) and the `public` schema.
4. Verify these source tables exist and contain rows:
   - `claims`
   - `fema_categories`
   - `documents`
   - `claim_status_history`

If any table is empty, submit one or two test claims through the app first so the sync has something to replicate.

---

## Part B — Create the destination catalog and schema

1. In the left nav, open **Catalog**.
2. If `fema_claims_workshop_catalog` does **not** exist, click **Create catalog** and create it.
3. Inside `fema_claims_workshop_catalog`, ensure a **`public`** schema exists. If not, click **Create schema** and name it `public`.

> The destination location **must** be `fema_claims_workshop_catalog.public` — the AI/BI dashboard the students will import is hard-coded to read from this location.

---

## Part C — Create a synced table for each source table

Repeat these steps **once per source table** (`claims`, `fema_categories`, `documents`, `claim_status_history`).

1. From the left nav, click **+ New → Add data**, then choose **Lakebase Postgres** (or open the Lakebase instance and click **Create → Synced table**).
2. **Source:**
   - **Database instance:** `fema-disaster-recovery`
   - **Database:** `databricks_postgres`
   - **Schema:** `public`
   - **Table:** the source table you are syncing (e.g. `claims`)
3. **Destination:**
   - **Catalog:** `fema_claims_workshop_catalog`
   - **Schema:** `public`
   - **Name:** **same name as the source** (e.g. `claims`). Do not rename — the dashboard queries these exact names.
4. **Sync mode:** **Continuous**.
5. **Primary key:** accept the primary key inferred from the Lakebase table (typically `id`).
6. Click **Create**.
7. Wait until the synced table status shows **Online / Active** and the initial snapshot completes. Small tables typically finish in under a minute.

After all four are created you should have:

| Source (Lakebase) | Destination (Lakehouse) |
|---|---|
| `public.claims` | `fema_claims_workshop_catalog.public.claims` |
| `public.fema_categories` | `fema_claims_workshop_catalog.public.fema_categories` |
| `public.documents` | `fema_claims_workshop_catalog.public.documents` |
| `public.claim_status_history` | `fema_claims_workshop_catalog.public.claim_status_history` |

---

## Part D — Verify the sync

1. Open the **SQL Editor** and attach to a running SQL warehouse.
2. Run a quick check against each synced table:

```sql
SELECT COUNT(*) FROM fema_claims_workshop_catalog.public.claims;
SELECT COUNT(*) FROM fema_claims_workshop_catalog.public.fema_categories;
SELECT COUNT(*) FROM fema_claims_workshop_catalog.public.documents;
SELECT COUNT(*) FROM fema_claims_workshop_catalog.public.claim_status_history;
```

3. Submit a new claim through the app, wait ~30 seconds, then re-run the `claims` count to confirm new rows propagate.

---

## Part E — Grant read access to the class

So students can query these tables from the AI/BI dashboard:

1. In **Catalog**, open `fema_claims_workshop_catalog`.
2. Click **Permissions → Grant**.
3. Grant **`USE CATALOG`** on the catalog and **`USE SCHEMA`** + **`SELECT`** on the `public` schema to the workshop group (or `account users` if that is what the workshop uses).

---

## You're done — the Lakehouse is now in sync with Lakebase

The students can now import the AI/BI dashboard and immediately see live data flowing from Lakebase through the synced tables.

## Need help?

- **Synced table stuck in "Provisioning":** Confirm the Lakebase instance is running and that the source table has a primary key.
- **`TABLE_OR_VIEW_NOT_FOUND` from the dashboard:** The destination catalog/schema/table names must match `fema_claims_workshop_catalog.public.<source_name>` exactly.
- **No new rows showing up:** Check the synced table's **Sync status** tab for the last successful sync timestamp and any error messages.
