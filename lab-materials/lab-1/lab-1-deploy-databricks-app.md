# Lab 1: Deploying a Databricks App

**Goal:** Sign in to your Databricks workspace, bring the **Disaster Recovery Tracker** sample app into the workspace from GitHub, and deploy it as a **Databricks App**.

**Repository:** [https://github.com/scottblackdb/disaster-recovery-tracker](https://github.com/scottblackdb/disaster-recovery-tracker)

---

## Before you start

- Use the **Databricks workspace URL** your instructor gives you (bookmark it if helpful).
- Note any **resource names** (Lakebase, catalog, project) the instructor provides—the sample `app.yaml` references team-specific resources you may need to align with your environment.

---

## Part A — Open the workspace

1. Open a **new browser tab** (or window).
2. Go to the **Databricks workspace URL** provided by your instructor.
3. **Sign in** with the credentials.
4. Confirm you see the Databricks **workspace home**.

---

## Part B — Clone the repository into the workspace

You will copy the app source from GitHub into Databricks so the platform can build and run it.

1. In the Databricks UI, open **Workspace** (or **Repos**, depending on your workspace layout).
2. Choose a folder where you keep course work (for example under your user folder), or use the path your instructor specifies.
3. **Add** or **Create** a Git-backed folder:
   - Select **GitHub** (or **Repos** → **Add repo**) as the source type.
   - When prompted for the repository URL, enter:
     - `https://github.com/scottblackdb/disaster-recovery-tracker`
   - If the UI asks for **branch**, use `main` unless your instructor names another branch.
4. Complete authentication if GitHub asks you to authorize Databricks (follow on-screen prompts).
5. Wait until the repository **finishes cloning** and you can browse files such as `app.yaml`, `backend/`, and `frontend/` in the file browser.

**Checkpoint:** You can open `app.yaml` in the workspace and see the app command and resources section.

---

## Part C — Understand what you cloned (short read)

Skim these items so deployment choices make sense:

| Item | Role |
|------|------|
| `app.yaml` | Tells Databricks Apps how to start the app (`uvicorn` on port 8000) and which resources (e.g. Lakebase) to attach. |
| `backend/` | Python **FastAPI** app (`backend.main:app`). |
| `frontend/` | Web UI built into static files for production (Dockerfile builds it; local dev may differ). |
| `Dockerfile` | Image build steps if your deployment path uses a container build. |

Ask your instructor if your class uses **pre-edited** `app.yaml` or environment-specific names before you deploy.

---

## Part D — Create Lakebase and add it as an app resource

The app needs a **Lakebase** (managed PostgreSQL) database. You will attached one named **`fema-disaster-recovery`**.

**Checkpoint:** You can see **`fema-disaster-recovery`** listed among your Lakebase / database resources.

### D.2 — Reference the database in `app.yaml` (required for deploy from repo)

The app declares its database binding in **`app.yaml`**. Update the `resources` block so it matches the Lakebase you created.

1. Open **`app.yaml`** at the root of your cloned repo in the workspace.
2. Find the `resources:` section. Replace the sample entry with a **postgres** resource whose **`name`** is **`fema-disaster-recovery`**, and set **`project`**, **`branch`**, and **`endpoint`** to the values that match **your** Lakebase instance (your instructor will tell you where to read these in the Lakebase UI or API).

Example shape (values are illustrative — use your real project / branch / endpoint):

```yaml
resources:
  - name: fema-disaster-recovery
    type: postgres
    project: <your-lakebase-project>
    branch: <your-branch>
    endpoint: <your-endpoint>
```

3. **Save** the file. If you use Git integration, **commit and push** when the instructor asks, or save in the workspace copy the app deployment reads.

> **Note:** The resource **`name`** (`fema-disaster-recovery`) is how the app binds to that database. It must stay consistent with what you attach in the deployment UI (below).

### D.3 — Add `fema-disaster-recovery` as a resource on the app

When you deploy (Part E), you must attach the same database:

1. In the **Create app** / **Deploy app** wizard, find **Resources**, **Dependencies**, or **Connected resources** (wording varies).
2. **Add resource** → choose **Postgres** / **Lakebase** (or the option your UI shows for PostgreSQL).
3. Select the Lakebase database **`fema-disaster-recovery`** you created in D.1.
4. Confirm the resource name matches the **`name`** in `app.yaml` (`fema-disaster-recovery`).

Do **not** deploy until this resource is attached (unless your instructor uses a different approved workflow).

---

## Part E — Deploy the Databricks App

Follow the flow your instructor demonstrates (UI labels can vary slightly by region and product version).

1. Open **Compute** → **Apps** (or **Apps** from the sidebar), depending on your workspace.
2. Choose **Create** or **Deploy app**.
3. Point the deployment at the **cloned repository path** in the workspace—the folder that contains `app.yaml` at its root.
4. Confirm the platform detects **`app.yaml`** and the start command (FastAPI / `uvicorn` on port **8000**).
5. Verify **environment variables** (for example `LLM_ENDPOINT`, `REFINE_LLM_ENDPOINT`, `ENDPOINT_NAME`) match what your instructor provided.
6. Verify the **`fema-disaster-recovery`** Lakebase resource is attached (see Part D.3).
7. **Deploy** (or **Save and deploy**) and wait for the build and health check to complete.
8. When the app shows **Running** (or equivalent), open the **app URL** from the Apps detail page.

**Checkpoint:** The Disaster Recovery Tracker UI loads in the browser and you can interact with it without a local machine running.

---

## Part F — Verify and wrap up

1. Load the app in a **fresh tab** using the link from the Apps UI.
2. Complete any **smoke test** your instructor assigns (for example: open a page, submit a test action).
3. Note the **app name** and **URL** for your lab report or next exercise.
4. If something fails, capture **screenshots** of the error and the **build / runtime logs** from the App’s detail page before asking for help.

## Need help?

- **Build fails:** Open build logs; missing `app.yaml` or wrong root folder is a common mistake.
- **Runtime errors:** Check app logs and confirm the **`fema-disaster-recovery`** resource in `app.yaml` matches the Lakebase instance and that the app’s **Resources** list includes that database.

Your instructor may provide a **known-good** fork or branch if the public `main` branch is updated during the course.
