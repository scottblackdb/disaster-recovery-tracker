# Lab 1.1: Creating a New Claim with AI Assistance

**Goal:** This lab walks you through the process of creating a new disaster recovery claim using the application, demonstrating how Databricks Foundational Models analyze images to assist with descriptions and categorization, and how Unity Catalog Volumes securely store your claim documents.

## Part A — Navigate to the New Claim Form

1.  Open the Disaster Recovery Tracker application in your web browser.
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

5.  **Submitted By:** This field will be pre-fill with your email address used to log into the app.
    
6.  **FEMA Category (optional - AI can suggest):** Leave this set to **"Let AI Suggest"**. We'll let the Databricks Foundational Model determine the category based on the image analysis.

## Part C — Utilize AI for Document Analysis and Categorization

This section demonstrates the power of Databricks Foundational Models in accelerating the claims process by analyzing documents.

1.  **Document Upload:** In the section titled "Describe damage from a photo (optional)" (which also handles documents), click **"Choose image file"** (it functions for documents too) or use the **"Or image URL"** field. For this lab, you can select one of the PDF estimate files from the `/lab-materials/damage_assets/` directories.
    *   *Example:* You can choose `tree_impact_restoration_estimate.pdf` from `/lab-materials/damage_assets/example_2/`.
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

## You have successfully created a claim with AI-assisted damage description and categorization, and ensured your supporting documents are stored in Unity Catalog Volumes!