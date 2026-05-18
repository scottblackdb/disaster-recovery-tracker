# Lab 1.1: Creating a New Claim with AI Assistance

**Goal:** This lab walks you through the process of creating a new disaster recovery claim using the application, demonstrating how Databricks Foundational Models analyze images to assist with descriptions and categorization, and how Unity Catalog Volumes securely store your claim documents.

## Part A — Navigate to the New Claim Form

1.  Open the Disaster Recovery Tracker application in your web browser. Here is a link to the application on the **Overview** section of the application.
2.  Locate and click on the **"Submit Claim"** button/link, found in the top left corner.

## Part B — Fill Out Initial Claim Details

On the "Submit New Claim" form, you will find several fields to provide details about the incident.

1.  **Incident Name:** Enter a descriptive name for the incident.
    *   *Example: "Hurricane Gemini 2026"*
2.  **County:** Enter the affected county.
    *   *Example: "Montgomery County"*
3.  **Applicant Name:** Enter the name of the person or entity making the claim.
    *   *Example: "John Doe"*
4.  **Estimated Cost ($):** Leave this field blank for now. The AI may populate it automatically based on the document you upload in Part C.

5.  **Submitted By:** This field will be pre-filled with your email address used to log into the app.
    
6.  **FEMA Category (optional - AI can suggest):** Leave this set to **"Let AI Suggest"**. We'll let the Databricks Foundational Model determine the category based on the image analysis. Do not create the claim just yet.

## Part C — Utilize AI for Document Analysis and Categorization

This section demonstrates the power of Databricks Foundational Models in accelerating the claims process by analyzing documents.

1.  **Document Upload:** In the section titled "Describe damage from a photo (optional)" (which also handles documents), click **"Choose image file"** (it functions for documents too) or use the **"Or image URL"** field. For this lab, use one of the JPG and one PDF estimate files included in the workshop materials downloaded to your laptop. They can be found in the `lab-materials/damage_assets/` folder of the repository you cloned.
    *   *Example:* You can choose `tree_impact_restoration_estimate.pdf` from `lab-materials/damage_assets/example_2/` 

    * or here is the URL `https://github.com/scottblackdb/disaster-recovery-tracker/tree/main/lab-materials/damage_assets`

    * Save both the JPG and PDF to your local machine.
    * Only upload the JPG. The PDF will be used later.

2.  **Initiate AI Analysis:** Click the **"Fill description from image"** button (this button processes documents as well).
    *   **Behind the Scenes (Databricks Foundational Models):** The application sends this PDF to the backend. The backend uses Databricks Foundational Models, specifically the `ai_parse_document` function, to read the PDF. This function intelligently extracts key information such as incident details, estimated costs, and damage descriptions. It then uses this extracted data to automatically populate the "Description of Damage / Work Needed" field and attempts to classify the damage to suggest a **FEMA Category**.
3.  **Review AI-Generated Description and Cost:** Observe that the **"Description of Damage / Work Needed"** text area is automatically populated with the AI's analysis of the document. Also, note that the **"Estimated Cost ($)"** field, which you left blank, might now be populated by the AI if it successfully extracted a cost from the PDF.
4.  **Refine Description (Optional):** If you wish to further enhance the description for clarity or FEMA compliance, you can click **"Refine with AI"**. This uses another AI model to clean up grammar and formatting. Review the suggested refinement and choose to "Use Refined Version" or "Keep Original".

## Part D — Submit Your Claim

Once you are satisfied with the claim details, including the AI-generated description:

1.  Click the **"Submit Claim"** button.
2.  **Behind the Scenes (Unity Catalog Volumes):** Upon submission, the image you provided via URL (or any uploaded files) is securely stored in **Unity Catalog Volumes**. This ensures that all documentation related to the claim is centralized, versioned, and governed within your Databricks environment. These volumes provide reliable and scalable storage for all attached files.
3.  **Claim Confirmation:** You will be redirected to the newly created claim's detail page, where you can review all the information and see the AI-assigned FEMA category (if one was suggested).
4. By leveraging Unity Catalog volumes you did not need another service to provide a filesystem for your app, this is what is meant by Unity Catalog is more than just a table catalog.

## Part E — Attach the PDF Estimate to Your Claim

In Part C you uploaded a **JPG** to draft the damage description. Now you'll attach the **PDF estimate** you saved to your local machine to the claim itself, so the app can run a deeper, structured extraction against it.

1.  **Locate your claim.** From the confirmation page in Part D you should already be on the claim's detail view. 
2.  **Find the Documents panel.** Scroll to the **"Documents"** section on the claim detail page. You'll see an upload control with **"Choose File"** (or a toggle for **File / URL**).
3.  **Upload the PDF estimate.** Click **"Choose File"** and select the PDF you saved in Part C — for example `tree_impact_restoration_estimate.pdf` from `lab-materials/damage_assets/example_2/`.
4.  **Watch it process.** The button changes to **"Processing with AI..."**. Behind the scenes the app:
    *   Uploads the PDF to the **Unity Catalog Volume** attached to the app (`/Volumes/fema/default/filestore/claim_<id>/...`).
    *   Inserts a row in the `documents` table with status `processing`.
    *   Calls the **Databricks SQL Warehouse** to run a single statement built from two **Databricks Foundation Model** functions:

        ```sql
        SELECT ai_extract(
          ai_parse_document('/Volumes/fema/default/filestore/claim_<id>/<file>.pdf'),
          ARRAY('vendor_name', 'total_cost', 'document_date', 'fema_category')
        ) AS extracted_json;
        ```

    *   `ai_parse_document` uses a Databricks-hosted vision/LLM model to read the PDF (text and layout) and return the document content as text. `ai_extract` then uses an LLM to pull out the specific structured fields you asked for, returning JSON like `{ "vendor_name": {"value": "..."}, "total_cost": {"value": "..."} ... }`.
5.  **Review what the AI populated.** When processing finishes (typically 10–30 seconds), the page refreshes and you should see, on the document row and the claim header:
    *   **Vendor**, **Extracted cost**, and **Document date** filled on the document.
    *   **FEMA Category** set on the claim if it was still on *"Let AI Suggest"*.
    *   **Estimated Cost ($)** auto-filled on the claim if you left it blank in Part B.
    *   **Status** advanced from *Submitted* / *AI Processed* to **Under Review** — successful structured extraction is the trigger.
6.  **Open the document.** Click the document's filename (or the open icon) to download/preview it from the Unity Catalog Volume — proving the file is governed and centrally stored, not on the app server's local disk.

> **Why two AI calls instead of one?** `ai_parse_document` is purpose-built for **document understanding** — it preserves headings, tables, and reading order from the PDF before any LLM sees it. `ai_extract` is then aimed at **schema-driven extraction** — given that clean text and a list of fields, it returns reliable JSON. Splitting the work this way is more accurate than asking a single general-purpose chat model to "read this PDF and give me JSON," and because both functions run inside Databricks SQL on a serverless warehouse, you get governance, auditability, and no extra service to manage.

## You have successfully created a claim with AI-assisted damage description and categorization, and ensured your supporting documents are stored in Unity Catalog Volumes!