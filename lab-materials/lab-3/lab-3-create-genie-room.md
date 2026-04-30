# Lab 3: Build a Genie Room for the FEMA Claims Data

**Goal:** Create a **Databricks AI/BI Genie space** over the FEMA claims tables so any user — including non-technical business users — can ask natural-language questions and get answers backed by governed SQL.

**Tables used:** `fema_claims_workshop_catalog.public.*` (the same tables the AI/BI dashboard from **Lab 2** queries).

---

## Before you start

- **Lab 2 (instructor steps)** must be complete — the Lakebase → Lakehouse synced tables must already exist in `fema_claims_workshop_catalog.public.*`.
- You need a running **SQL warehouse** (Serverless is fine).
- You need permission to **create a Genie space** and **`SELECT`** on the four claims tables.

---

## Part A — Create a new Genie space

1. In the Databricks workspace left nav, click **Genie**.
2. Click **+ New** (top right) → **New Genie space**.
3. Name the space **`FEMA Claims Genie`**.
4. Pick the **SQL warehouse** you want Genie to run queries on.
5. Click **Create**.

---

## Part B — Add the claims tables to the space

In the space's **Data** panel:

1. Click **Add tables**.
2. Browse to `fema_claims_workshop_catalog` → `public` and add **all four** tables:
   - `claims`
   - `fema_categories`
   - `documents`
   - `claim_status_history`
3. Click **Confirm**.

> Genie reads the tables' schemas and column comments automatically. The richer the table comments, the better Genie's answers will be.

---

## Part C — Give Genie business context (instructions)

Genie answers are dramatically better when you tell it **what the data means**, not just **what columns exist**. Open the space's **Instructions** tab and paste the following as general instructions:

```text
This Genie space answers questions about FEMA disaster recovery claims submitted
through the Disaster Recovery Tracker app.

Key tables:
- claims: one row per submitted disaster-recovery claim. Key columns:
    * status: lifecycle stage. Common values: 'submitted', 'ai_processed', 'approved', 'rejected'.
    * estimated_cost: applicant-provided or AI-extracted estimated repair cost (USD).
    * approved_amount: amount FEMA has approved so far (USD). NULL until approved.
    * ai_confidence_score: 0.0–1.0 confidence the AI had when categorizing the claim.
    * submitted_at: when the claim was submitted (UTC timestamp).
    * fema_category_id: foreign key to fema_categories.id.
- fema_categories: lookup table of FEMA damage categories (code + descriptive name).
- documents: supporting documents attached to a claim. claim_id joins to claims.id.
- claim_status_history: audit log of every status transition for a claim.

Default joins:
- claims.fema_category_id = fema_categories.id (LEFT JOIN — categories are optional)
- documents.claim_id = claims.id
- claim_status_history.claim_id = claims.id

Default behavior:
- "Total claims" means COUNT(*) over claims.
- "Claim amount" or "claim value" defaults to estimated_cost; use approved_amount only if the user says "approved".
- "Recent" / "this week" / "today" should filter on submitted_at unless the user references a status change.
- Always COALESCE category names to 'Uncategorized' when grouping by category.
```

Save the instructions.

---

## Part D — Add sample questions

Sample questions are what users see the moment they open the space. They double as **few-shot examples** Genie uses to learn how to write queries against your tables. Open the **Sample questions** tab and add the following:

### Volume & status
1. How many claims have been submitted in total?
2. How many claims are in each status?
3. How many claims were submitted this week?
4. How many claims are still in `submitted` status (not yet AI-processed or approved)?

### Cost & approval
5. What is the total estimated cost across all claims?
6. What is the total approved amount so far?
7. What is the approval rate (approved claims / total claims)?
8. What is the average estimated cost per FEMA category?

### Geography & incidents
9. Which county has the highest total estimated cost?
10. Show me the top 5 incidents by number of claims.
11. Which incident has the largest total approved amount?

### FEMA categories
12. How many claims fall into each FEMA category?
13. Which FEMA category has the highest average estimated cost?
14. How many claims are uncategorized?

### AI quality signals
15. How many claims have an AI confidence score below 0.5?
16. What is the average AI confidence score by FEMA category?

### Documents
17. What percentage of claims have at least one supporting document?
18. Which file types are most common across supporting documents?
19. Which claim has the most attached documents?

### Activity & history
20. Show me the 10 most recent status changes.
21. Which user has changed the most claim statuses?
22. Which claims moved from `submitted` to `approved` in the last 7 days?

---

## Part E — Test the space

1. Click **New chat** in the Genie space.
2. Try a few sample questions and a few of your own:
   - *"Which counties had more than 5 claims last month?"*
   - *"What's the median estimated cost for claims with AI confidence above 0.8?"*
3. For each answer, click **Show generated code** to see the SQL Genie wrote and verify it ran against `fema_claims_workshop_catalog.public.*`.
4. If a question produces a wrong or awkward query, click **👎** and add a **Verified answer** with the correct SQL. Genie will use that pattern next time.

---

## Part F — Share the space

1. Click **Share** in the top right of the space.
2. Add the workshop group (or `account users`) with **Can run** permission.
3. Optionally enable **embedding** so the Genie space can be dropped into the AI/BI dashboard from **Lab 2** as a tile.

---

## Part G — Try the Genie space in Databricks One

So far you've used Genie inside the **full Databricks workspace** — the same UI engineers and analysts use. But Genie's audience is usually **business users** who shouldn't have to see notebooks, jobs, or catalogs. **Databricks One** is the simplified, consumer-grade UI built exactly for them: no left nav full of engineering tools — just the AI/BI dashboards and Genie spaces that have been shared with the user.

### Open Databricks One

1. Open a **new browser tab**.
2. Go to your workspace URL with `/one` appended, for example:
   `https://<your-workspace>.cloud.databricks.com/one`
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

1. From the Databricks One home page, click the **`fema_claims_overview`** dashboard you imported in **Lab 2**.
2. Interact with it the same way you did before — cross-filtering, refreshing, scrolling to the **AI Forecast** tiles.

### Why this matters

- **One product, two front doors.** Engineers use the full workspace; business users use Databricks One. Both hit the **same** governed tables, the **same** Genie space, and the **same** AI/BI dashboard. There is nothing to copy, sync, or rebuild.
- **No training required.** A claims adjuster who has never used Databricks can sign in to `/one`, click the Genie tile, and ask *"How many claims came in from Montgomery County yesterday?"* — and get a correct, governed answer with a chart.
- **Same governance.** Unity Catalog permissions, row/column filters, and lineage apply identically in Databricks One. A user who can't see a column in SQL can't see it through Genie either.

## Congratulations — your business users now have a self-service Genie!

Together with **Lab 1** (the app writing into Lakebase) and **Lab 2** (Lakebase → Lakehouse sync + AI/BI dashboard), you now have an end-to-end stack where:

- **Operators** submit and manage claims in the Databricks App.
- **Analysts** explore curated visuals in the AI/BI dashboard.
- **Anyone** asks ad-hoc questions in plain English through the Genie space — backed by the same governed Unity Catalog tables.

## Need help?

- **Genie says it can't find a table:** Confirm the four tables are listed under the **Data** tab and that you have `SELECT` on `fema_claims_workshop_catalog.public.*`.
- **Answers reference the wrong column** (e.g. uses `approved_amount` when you said "claim cost"): Tighten the **Instructions** in Part C — Genie heavily weights instruction text over column names alone.
- **Queries are slow:** Switch the space to a larger or Serverless SQL warehouse in the space's settings.
- **A specific question always answers wrong:** Add a **Verified answer** with the correct SQL — Genie will reuse it for similar future questions.
- **Databricks One is empty / the Genie space is missing:** The space hasn't been shared with your user yet. Re-check **Part F** and confirm your account is in the group you granted **Can run** to.
- **`/one` URL doesn't load:** Databricks One must be enabled at the account level. If it isn't, click your profile picture → **Switch to Databricks One**, or ask your account admin to enable it.
