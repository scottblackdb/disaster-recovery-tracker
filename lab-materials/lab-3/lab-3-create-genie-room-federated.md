# Lab 3 (Federated): Build a Genie Room for the FEMA Claims Data

**Goal:** Create a **Databricks Genie space** over the FEMA claims tables so any user — including non-technical business users — can ask natural-language questions and get answers backed by governed SQL.

**Tables used:** `fema_lakebase.public.*` (the same tables the federated AI/BI dashboard from **Lab 2** queries).

> **This is the federated version of Lab 3.** If your instructor set up the CDC/sync approach instead, follow [`lab-3-create-genie-room.md`](./lab-3-create-genie-room.md) — same exercise, but that version points at the synced `fema.bronze.*` tables.

---

## Before you start

- **Lab 2 (instructor steps)** must be complete — the Lakebase database must already be registered in Unity Catalog as the **`fema_lakebase`** catalog.
- You need access to a SQL warehouse with **serverless compute enabled** (shown as **Serverless** in the warehouse list). Federated Lakebase catalogs cannot be queried by a non-serverless warehouse.
- You need permission **`SELECT`** on the four claims tables.

---

## Part A — Create a new Genie space

1. In the Databricks workspace left nav, click **Genie Spaces**.
2. Click **+ New** (top right).
3. When prompted, name the space **`FEMA Claims Genie`**.
4. Browse to `fema_lakebase` → `public` and add **all four** tables:
   - `claims`
   - `fema_categories`
   - `documents`
   - `claim_status_history`
5. Make sure the space's SQL warehouse is set to a **Serverless** warehouse.

---

> Genie reads the tables' schemas and column comments automatically. The richer the table comments, the better Genie's answers will be.

---

## Part B — Give Genie business context (instructions)

Genie answers are dramatically better when you tell it **what the data means**, not just **what columns exist**. Open the space's **Instructions** tab in the top right corner and paste the following as general instructions:

```text
This Genie space answers questions about FEMA disaster recovery claims submitted
through the Disaster Recovery Tracker app.

The tables live in fema_lakebase.public and are queried live from the Lakebase
Postgres (OLTP) database through Lakehouse Federation. Each row is the CURRENT
state of a record — there is no history, no versioning, and no soft-deleted rows
to filter out.

Key tables:
- claims: one row per claim. Key columns:
    * status: lifecycle stage. Common values: 'submitted', 'ai_processed', 'approved', 'rejected'.
    * estimated_cost: applicant-provided or AI-extracted estimated repair cost (USD).
    * approved_amount: amount FEMA has approved so far (USD). NULL until approved.
    * ai_confidence_score: 0.0–1.0 confidence the AI had when categorizing the claim.
    * submitted_at: when the claim was submitted (UTC timestamp).
    * updated_at: when the claim was last modified (UTC timestamp).
    * county, incident_name, applicant_name: who and where the claim covers.
    * fema_category_id: foreign key to fema_categories.id.
- fema_categories: lookup table of FEMA damage categories (code + descriptive name).
- documents: supporting documents attached to a claim. claim_id joins to claims.id.
- claim_status_history: audit log of every status transition for a claim.

Default behavior:
- "Total claims" means COUNT(*) over claims — one row per claim, so no deduplication is needed.
- "Claim amount" or "claim value" defaults to estimated_cost; use approved_amount only if the user says "approved".
- "Recent" / "this week" / "today" should filter on submitted_at unless the user references a status change.
- Always COALESCE category names to 'Uncategorized' when grouping by category.

Default joins:
- claims.fema_category_id = fema_categories.id (LEFT JOIN — categories are optional)
- documents.claim_id = claims.id
- claim_status_history.claim_id = claims.id
```

Save the instructions.

> **Why these instructions are shorter than the synced version:** with the CDC/sync approach the tables are SCD Type 2, so Genie has to be told to deduplicate to the latest version of each record and skip deletes. Federated tables are already current-state, so that whole class of instruction — and the mistakes Genie makes when it forgets them — simply doesn't apply.

---

## Part C — Add sample questions

On the About tab there are a few sample questions. Sample questions are what users see the moment they open the space. They double as **few-shot examples** Genie uses to learn how to write queries against your tables. Open the **Sample questions** tab and add the following:

### Volume & status
1. How many claims have been submitted in total?
2. How many claims are in each status?

### Cost & approval
3. What is the total estimated cost across all claims?

### Geography & incidents
4. Which county has the highest total estimated cost?
5. Show me the top 5 incidents by number of claims.

### FEMA categories
6. How many claims fall into each FEMA category?

### Activity & history
7. Show me the 10 most recent status changes.
8. Which user has changed the most claim statuses?

---

## Part D — Save the space

1. Click **Save** in the top right of the Genie space editor.
2. Confirm the space title shows **`FEMA Claims Genie`** in the breadcrumb.

---

## Part E — Test the space

1. Click **New chat** in the Genie space.
2. Try a few sample questions and a few of your own:
   - *"Which counties had more than 5 claims last month?"*
   - *"What's the median estimated cost for claims with AI confidence above 0.8?"*
   - *"How many claims were submitted this week?"*
   - *"What is the total approved amount so far?"*
   - *"Which county has the highest total estimated cost?"*

3. For each answer, click **Show generated code** to see the SQL Genie wrote and verify it ran against `fema_lakebase.public.*`.
4. If a question produces a wrong or awkward query, click **👎**. Administrators can review and correct wrong answers to improve Genie over time.

> **Try this:** submit a new claim in the app (Lab 1.1 steps), then immediately ask Genie *"How many claims were submitted today?"*. Because Genie is querying Postgres live through the federated catalog, your claim is already counted — there's no sync to wait for.

---

## Part F — Share the space

1. Click **Share** in the top right of the space.
2. Add the workshop group (or `account users`) with **Can run** permission.

---

## Part G — Try the Genie space in Databricks One

So far you've used Genie inside the **full Databricks workspace** — the same UI engineers and analysts use. But Genie's audience is usually **business users** who shouldn't have to see notebooks, jobs, or catalogs. **Databricks One** is the simplified, consumer-grade UI built exactly for them: no left nav full of engineering tools — just the AI/BI dashboards and Genie spaces that have been shared with the user.

### Open Databricks One

1. Open a **new browser tab**.
2. Go to your workspace URL with `/one` appended, for example:
   `https://<your-workspace url>/one`
   *(If that doesn't load, click your profile picture in the top-right of the workspace and choose **Switch to Databricks One**.)*
3. Sign in with the same credentials you've been using.

You should land on a clean home page that lists the dashboards and Genie spaces shared with you — and **nothing else**. No clusters, no notebooks, no SQL editor.

### Ask Genie a question from Databricks One

1. Click the **`FEMA Claims Genie`** space you created in Part A.
2. Try the same kind of questions you tried in Part E:
   - *"How many claims were submitted this week?"*
   - *"Which county has the highest total estimated cost?"*
   - *"What's the average AI confidence score by FEMA category?"*
3. Notice that the answer, the chart, and the **Show generated code** option are all still there — Databricks One is a simpler **wrapper**, not a less-capable product.

### Open the Lab 2 dashboard from Databricks One

1. From the Databricks One home page, click the **`fema_claims_overview_federated`** dashboard you imported in **Lab 2**.
2. Interact with it the same way you did before — cross-filtering, refreshing, scrolling to the **AI Forecast** tiles.

### Why this matters

- **One product, two front doors.** Engineers use the full workspace; business users use Databricks One. Both hit the **same** governed tables, the **same** Genie space, and the **same** AI/BI dashboard. There is nothing to copy, sync, or rebuild.
- **No training required.** A claims adjuster who has never used Databricks can sign in to `/one`, click the Genie tile, and ask *"How many claims came in from Montgomery County yesterday?"* — and get a correct, governed answer with a chart.
- **Same governance.** Unity Catalog permissions, row/column filters, and lineage apply identically in Databricks One. A user who can't see a column in SQL can't see it through Genie either.

## Congratulations — your business users now have a self-service Genie!

Together with **Lab 1** (the app writing into Lakebase) and **Lab 2** (registering Lakebase in Unity Catalog + the AI/BI dashboard), you now have an end-to-end stack where:

- **Operators** submit and manage claims in the Databricks App.
- **Analysts** explore curated visuals in the AI/BI dashboard.
- **Anyone** asks ad-hoc questions in plain English through the Genie space — backed by the same governed Unity Catalog tables.

And because Lab 2 used **Lakehouse Federation** rather than a sync, all three of those audiences are reading the **same live Postgres rows**. There is no pipeline to fall behind, and no window where the dashboard and the app disagree.

## Need help?

- **Genie says it can't find a table:** Confirm the four tables are listed under the **Data** tab and that you have `SELECT` on `fema_lakebase.public.*`.
- **Genie returns a permission error on every question:** The space's SQL warehouse must have **serverless compute enabled** — federated Lakebase catalogs can't be queried by a non-serverless warehouse. Change it in the space settings.
- **Answers reference the wrong column** (e.g. uses `approved_amount` when you said "claim cost"): Tighten the **Instructions** in Part B — Genie heavily weights instruction text over column names alone.
- **A specific question always answers wrong:** Add a **Verified answer** with the correct SQL — Genie will reuse it for similar future questions.
- **Databricks One is empty / the Genie space is missing:** The space hasn't been shared with your user yet. Re-check **Part F** and confirm your account is in the group you granted **Can run** to.
