# Lab 3: Build a Genie Agent for the FEMA Claims Data

**Goal:** Create a **Databricks Genie agent** over the FEMA claims tables so any user — including non-technical business users — can ask natural-language questions and get answers backed by governed SQL.

**Tables used:** `fema.bronze.`* (the same tables the AI/BI dashboard from **Lab 2** queries).

---

## Before you start

- **Lab 2 (instructor steps)** must be complete — the Lakebase → Lakehouse synced tables must already exist in `fema.bronze.`*.
- You need access to **a SQL warehouse**.
- You need permission `SELECT` on the four claims tables.

---



## Part A — Create a new Genie agent

1. In the Databricks workspace left nav, click **Genie Agents**.
2. Click **+ New** (top right).
3. When prompted, name the agent `FEMA Claims Genie <Your Name>`.
4. Browse to `fema` → `bronze` and add **all four** tables:
  - `lb_claims_history`
  - `lb_fema_categories_history`
  - `lb_documents_history`
  - `lb_claim_status_history_history`

---

> Genie reads the tables' schemas and column comments automatically. The richer the table comments, the better Genie's answers will be.

---



## Part B — Give Genie business context (instructions)

Genie answers are dramatically better when you tell it **what the data means**, not just **what columns exist**. Open the agent's **Instructions** tab in the top right corner and paste the following as general instructions:

```text
This Genie agent answers questions about FEMA disaster recovery claims submitted
through the Disaster Recovery Tracker app.

Key tables (all in fema.bronze, SCD Type 2 — each row represents one version of a record):
- lb_claims_history: one row per claim version. Key columns:
    * status: lifecycle stage. Common values: 'submitted', 'ai_processed', 'approved', 'rejected'.
    * estimated_cost: applicant-provided or AI-extracted estimated repair cost (USD).
    * approved_amount: amount FEMA has approved so far (USD). NULL until approved.
    * ai_confidence_score: 0.0–1.0 confidence the AI had when categorizing the claim.
    * submitted_at: when the claim was submitted (UTC timestamp).
    * fema_category_id: foreign key to lb_fema_categories_history.id.
- lb_fema_categories_history: lookup table of FEMA damage categories (code + descriptive name).
- lb_documents_history: supporting documents attached to a claim. claim_id joins to lb_claims_history.id.
- lb_claim_status_history_history: audit log of every status transition for a claim.

Default behavior:
- "Total claims" means COUNT(DISTINCT id) over lb_claims_history using the latest version of each record.
- "Claim amount" or "claim value" defaults to estimated_cost; use approved_amount only if the user says "approved".
- "Recent" / "this week" / "today" should filter on submitted_at unless the user references a status change.
- Always COALESCE category names to 'Uncategorized' when grouping by category.

Default joins:
- lb_claims_history.fema_category_id = lb_fema_categories_history.id (LEFT JOIN — categories are optional)
- lb_documents_history.claim_id = lb_claims_history.id
- lb_claim_status_history_history.claim_id = lb_claims_history.id
```

Save the instructions.

---



## Part C — Add sample questions

On the About tab there are a few sample questions. Sample questions are what users see the moment they open the agent. They double as **few-shot examples** Genie uses to learn how to write queries against your tables. Open the **Sample questions** tab and add the following:

### Volume & status

1. How many claims have been submitted in total?
2. How many claims are in each status?



### Cost & approval

1. What is the total estimated cost across all claims?



### Geography & incidents

1. Which county has the highest total estimated cost?
2. Show me the top 5 incidents by number of claims.



### FEMA categories

1. How many claims fall into each FEMA category?



### Activity & history

1. Show me the 10 most recent status changes.
2. Which user has changed the most claim statuses?

---



## Part D — Save the agent

1. Click **Save** in the top right of the Genie agent editor.
2. Confirm the agent title shows `FEMA Claims Genie` in the breadcrumb.

---



## Part E — Test the agent

1. Click **New chat** in the Genie agent.
2. Try a few sample questions and a few of your own:
  - *"Which counties had more than 5 claims last month?"*
  - *"What's the median estimated cost for claims with AI confidence above 0.8?"*
  - *"How many claims were submitted this week?"*
  - *"What is the total approved amount so far?"*
  - *"Which county has the highest total estimated cost?"*
3. For each answer, click **Show generated code** to see the SQL Genie wrote and verify it ran against `fema.bronze.`*.
4. If a question produces a wrong or awkward query, click **👎**.  Administrators can review and correct wrong answers to improve Genie over time.

---



## Part F — Share the agent

1. Click **Share** in the top right of the agent.
2. Add the workshop group (or `account users`) with **Can run** permission.

---



## Part G — Try the Genie agent in Databricks One

So far you've used Genie inside the **full Databricks workspace** — the same UI engineers and analysts use. But Genie's audience is usually **business users** who shouldn't have to see notebooks, jobs, or catalogs. **Databricks One** is the simplified, consumer-grade UI built exactly for them: no left nav full of engineering tools — just the AI/BI dashboards and Genie agents that have been shared with the user.

### Open Databricks One

1. Open a **new browser tab**.
2. Go to your workspace URL with `/one` appended, for example:
  `https://<your-workspace url>/one`
   *(If that doesn't load, click your profile picture in the top-right of the workspace and choose **Switch to Databricks One**.)*
3. Sign in with the same credentials you've been using.

You should land on a clean home page that lists the dashboards and Genie agents shared with you — and **nothing else**. No clusters, no notebooks, no SQL editor.

### Ask Genie a question from Databricks One

1. Click the `FEMA Claims Genie` agent you created in Part A.
2. Try the same kind of questions you tried in Part E:
  - *"How many claims were submitted this week?"*
  - *"Which county has the highest total estimated cost?"*
  - *"What's the average AI confidence score by FEMA category?"*
3. Notice that the answer, the chart, and the **Show generated code** option are all still there — Databricks One is a simpler **wrapper**, not a less-capable product.



### Open the Lab 2 dashboard from Databricks One

1. From the Databricks One home page, click the `fema_claims_overview` dashboard you imported in **Lab 2**.
2. Interact with it the same way you did before — cross-filtering, refreshing, scrolling to the **AI Forecast** tiles.



### Why this matters

- **One product, two front doors.** Engineers use the full workspace; business users use Databricks One. Both hit the **same** governed tables, the **same** Genie agent, and the **same** AI/BI dashboard. There is nothing to copy, sync, or rebuild.
- **No training required.** A claims adjuster who has never used Databricks can sign in to `/one`, click the Genie tile, and ask *"How many claims came in from Montgomery County yesterday?"* — and get a correct, governed answer with a chart.
- **Same governance.** Unity Catalog permissions, row/column filters, and lineage apply identically in Databricks One. A user who can't see a column in SQL can't see it through Genie either.



## Congratulations — your business users now have a self-service Genie!

Together with **Lab 1** (the app writing into Lakebase) and **Lab 2** (Lakebase → Lakehouse sync + AI/BI dashboard), you now have an end-to-end stack where:

- **Operators** submit and manage claims in the Databricks App.
- **Analysts** explore curated visuals in the AI/BI dashboard.
- **Anyone** asks ad-hoc questions in plain English through the Genie agent — backed by the same governed Unity Catalog tables.



## Need help?

- **Genie says it can't find a table:** Confirm the four tables are listed under the **Data** tab and that you have `SELECT` on `fema.bronze.`*.
- **Answers reference the wrong column** (e.g. uses `approved_amount` when you said "claim cost"): Tighten the **Instructions** in Part C — Genie heavily weights instruction text over column names alone.
- **A specific question always answers wrong:** Add a **Verified answer** with the correct SQL — Genie will reuse it for similar future questions.
- **Databricks One is empty / the Genie agent is missing:** The agent hasn't been shared with your user yet. Re-check **Part F** and confirm your account is in the group you granted **Can run** to.

