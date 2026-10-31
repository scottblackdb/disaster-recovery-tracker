# Disaster Recovery Tracker

A **3-hour hands-on workshop** for public-sector organizations. Participants deploy a working FEMA Public Assistance claims app on **Databricks Apps**, store operational data in **Lakebase** (managed Postgres), and then use that same data for analytics, natural-language questions, and isolated database branches.

The scenario is a disaster-recovery claims desk: counties submit incidents, attach photos and contractor estimates, and get AI-assisted descriptions and FEMA PA categories. The point is not to build a production grants system. It is to show how an agency can run an operational application and a lakehouse on one Databricks platform.

**Repository:** [github.com/scottblackdb/disaster-recovery-tracker](https://github.com/scottblackdb/disaster-recovery-tracker)

---

## Who this is for

Program, IT, and data teams in state, local, tribal, and federal organizations who want a concrete walkthrough of:

- **Databricks Apps** — host a custom web application in the workspace, with identity, compute, and attached data resources.
- **Lakebase** — a Postgres OLTP database for the system of record (claims, documents, status history), with branching, autoscaling, and scale-to-zero.
- How operational data becomes governed analytics in **Unity Catalog** (synced Delta tables or live Lakehouse Federation).
- A short look at **AI/BI dashboards**, **Genie Agents**, **Unity Catalog Volumes** for files, and Databricks-hosted LLMs for document assist.

No prior Databricks experience is required. Participants should be comfortable in a browser and following a lab guide.

---

## What you will do

By the end of the session you will have:

1. Deployed the Disaster Recovery Tracker as a Databricks App from this GitHub repo.
2. Granted the app’s service principal access to the shared Lakebase database.
3. Submitted a claim with photo/PDF assist (foundation models + Volumes).
4. Analyzed claims in an AI/BI dashboard over Lakebase data in the lakehouse.
5. Asked natural-language questions with a Genie Agent.
6. Created a personal Lakebase branch, reviewed autoscaling, and pointed your app at that branch without changing shared production data.

---

## Suggested 3-hour agenda

Times are a guide. Instructors should keep Lab 1 moving; it is the longest student exercise.

| Time | Topic | Materials |
|------|--------|-----------|
| 0:00–0:15 | Welcome, public-sector scenario, architecture | This README |
| 0:15–1:20 | **Lab 1** — Deploy the App, grant Lakebase permissions, submit a claim | [lab-1-deploy-databricks-app.md](lab-materials/lab-1/lab-1-deploy-databricks-app.md), [lab-1.1-environment-variables.md](lab-materials/lab-1/lab-1.1-environment-variables.md), [lab-1.2-create-claim-tutorial.md](lab-materials/lab-1/lab-1.2-create-claim-tutorial.md) |
| 1:20–1:30 | Break | |
| 1:30–2:05 | **Lab 2** — Import the AI/BI dashboard | [lab-2.1-import-aibi-dashboard.md](lab-materials/lab-2/lab-2.1-import-aibi-dashboard.md) *(or the federated variant)* |
| 2:05–2:35 | **Lab 3** — Create a Genie Agent | [lab-3-create-genie-room.md](lab-materials/lab-3/lab-3-create-genie-room.md) *(or the federated variant)* |
| 2:35–2:55 | **Lab 4** — Lakebase branching and autoscaling | [lab-4-lakebase-branching-and-autoscale.md](lab-materials/lab-4/lab-4-lakebase-branching-and-autoscale.md) |
| 2:55–3:00 | Recap and questions | |

Sample damage photos and PDFs for Lab 1 live in [`lab-materials/damage_assets/`](lab-materials/damage_assets/).

---

## Architecture in one page

```
┌─────────────────────────────┐
│  Databricks App (this repo) │
│  FastAPI + React UI         │
└───────┬──────────┬──────────┘
        │          │
        │          ▼
        │   Unity Catalog Volume  (claim files / images)
        │
        ▼
  Lakebase Postgres           SQL warehouse
  (OLTP: claims, docs,        (analytics, AI functions
   status)                     on documents)
        │
        ▼
  Unity Catalog
  • Synced tables  fema.bronze.*
    or federated catalog  fema_lakebase.public.*
        │
        ├── AI/BI dashboard
        └── Genie Agent
```

- **Apps** run the UI and API in the workspace. `app.yaml` starts `uvicorn` and attaches Lakebase, a SQL warehouse, and a Volume.
- **Lakebase** is the transactional system of record. The default project/branch used by the app is `disaster-recovery-tracker` / `production`.
- **Volumes** store non-tabular evidence (photos, estimates) next to governed tables — no separate file service.
- **LLMs** used by the app are Unity Gateway model APIs (`system.ai.llama-4-maverick`, `system.ai.gpt-oss-120b`) plus SQL `ai_parse_document` / `ai_extract` for PDFs.

---

## Student labs

Complete these in order. Use the workspace URL and login your instructor provides.

| Lab | Goal |
|-----|------|
| [1 — Deploy the Databricks App](lab-materials/lab-1/lab-1-deploy-databricks-app.md) | Create `fema-claims-tracker-<your-name>` from Git (`main`), attach Lakebase / warehouse / Volume, grant the app SP database access |
| [1.1 — App environment variables](lab-materials/lab-1/lab-1.1-environment-variables.md) | How `app.yaml` injects warehouse ID, Volume path, and Lakebase connection |
| [1.2 — Submit a claim with AI](lab-materials/lab-1/lab-1.2-create-claim-tutorial.md) | Create a claim; use image/PDF assist and optional “Refine with AI” |
| [2.1 — AI/BI dashboard](lab-materials/lab-2/lab-2.1-import-aibi-dashboard.md) | Import `fema_claims_overview.lvdash.json` and explore claims |
| [3 — Genie Agent](lab-materials/lab-3/lab-3-create-genie-room.md) | Natural-language Q&A over the same tables |
| [4 — Lakebase branches](lab-materials/lab-4/lab-4-lakebase-branching-and-autoscale.md) | Personal copy-on-write branch, scale-to-zero, retarget your app |

If the instructor registered Lakebase with **Lakehouse Federation** instead of synced tables, use:

- [Lab 2.1 (federated)](lab-materials/lab-2/lab-2.1-import-aibi-dashboard-federated.md)
- [Lab 3 (federated)](lab-materials/lab-3/lab-3-create-genie-room-federated.md)

---

## Instructor setup

Run this **before** the session. Students should not run the setup script.

1. Authenticate the Databricks CLI (`databricks auth profiles`).
2. Provision Lakebase, Unity Catalog (`fema` catalog, `bronze` / `default` schemas, `filestore` volume), and workspace users:

   ```bash
   cd workshop_setup
   pip install -r requirements.txt
   python setup_workshop.py --profile <PROFILE> --users-file participants.txt
   ```

   Infra without a participant list: `--infra-only`. Other flags (`--lakebase-only`, `--uc-only`, `--users-only`) are documented in `workshop_setup/setup_workshop.py`.

3. After students have submitted at least one claim, expose Lakebase to the lakehouse using **one** of:

   - [Sync to Delta (`fema.bronze.*`)](lab-materials/lab-2/lab-2-instructor-sync-lakebase-to-lakehouse.md) — CDC-style history tables; students use the non-federated Lab 2.1 / Lab 3.
   - [Lakehouse Federation (`fema_lakebase`)](lab-materials/lab-2/lab-2-instructor-federate-lakebase.md) — live Postgres via Unity Catalog; students use the federated Lab 2.1 / Lab 3. The federated catalog name must stay `fema_lakebase`.

Granting the app `databricks_superuser` in Lab 1 is a **lab convenience**, not a production pattern. Call that out when you walk the class through permissions.

---

## Repository layout

| Path | Role |
|------|------|
| `app.yaml` | Databricks Apps start command, env, Lakebase resource |
| `backend/` | FastAPI API, Lakebase access, document AI |
| `frontend/` | React UI (production build is served with the app) |
| `lab-materials/` | Timed lab guides, dashboard JSON, sample damage files |
| `workshop_setup/` | Instructor environment bootstrap |

---

## Prerequisites for participants

- Browser and the workshop workspace URL / account from the instructor.
- Permission to create a Databricks App and to use a SQL warehouse.
- Optional: clone or download this repo locally so you can grab files from `lab-materials/damage_assets/` without using GitHub in the lab.

This workshop is a shared classroom environment. Do not put real PII, real claim packages, or production credentials into the app.
