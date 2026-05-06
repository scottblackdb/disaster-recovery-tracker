-- Disaster Recovery Tracker — Lakebase / PostgreSQL bootstrap
-- Executed automatically on app startup when core tables are missing.
-- Statements are split by "-- statement-break" (see db_bootstrap.py).

-- statement-break

CREATE TABLE IF NOT EXISTS fema_categories (
    id SERIAL PRIMARY KEY,
    code VARCHAR(8) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

-- statement-break

CREATE TABLE IF NOT EXISTS claims (
    id SERIAL PRIMARY KEY,
    incident_name TEXT NOT NULL,
    county TEXT NOT NULL,
    applicant_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    estimated_cost NUMERIC(14, 2),
    approved_amount NUMERIC(14, 2),
    submitted_by TEXT NOT NULL DEFAULT '',
    fema_category_id INTEGER REFERENCES fema_categories (id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'submitted',
    ai_confidence_score NUMERIC(10, 4),
    ai_flags TEXT,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- statement-break

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES claims (id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL DEFAULT '',
    file_size BIGINT NOT NULL DEFAULT 0,
    storage_path TEXT,
    ai_extracted_vendor TEXT,
    ai_extracted_cost NUMERIC(14, 2),
    ai_extracted_date DATE,
    ai_extracted_category TEXT,
    ai_summary TEXT,
    ai_damage_description TEXT,
    processing_status TEXT NOT NULL DEFAULT 'processing',
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- statement-break

CREATE TABLE IF NOT EXISTS claim_status_history (
    id SERIAL PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES claims (id) ON DELETE CASCADE,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by TEXT NOT NULL DEFAULT '',
    notes TEXT,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- statement-break

ALTER TABLE fema_categories REPLICA IDENTITY FULL;

-- statement-break

ALTER TABLE claims REPLICA IDENTITY FULL;

-- statement-break

ALTER TABLE documents REPLICA IDENTITY FULL;

-- statement-break

ALTER TABLE claim_status_history REPLICA IDENTITY FULL;

-- statement-break

CREATE INDEX IF NOT EXISTS idx_documents_claim_id ON documents (claim_id);

-- statement-break

CREATE INDEX IF NOT EXISTS idx_claim_status_history_claim_id ON claim_status_history (claim_id);

-- statement-break

INSERT INTO fema_categories (code, name, description) VALUES
    ('A', 'Debris Removal', 'FEMA Public Assistance Category A — debris removal.'),
    ('B', 'Emergency Protective Measures', 'FEMA Public Assistance Category B — emergency protective measures.'),
    ('C', 'Roads and Bridges', 'FEMA Public Assistance Category C — roads and bridges.'),
    ('D', 'Water Control Facilities', 'FEMA Public Assistance Category D — water control.'),
    ('E', 'Public Buildings and Contents', 'FEMA Public Assistance Category E — public buildings and contents.'),
    ('F', 'Public Utilities', 'FEMA Public Assistance Category F — public utilities.'),
    ('G', 'Parks, Recreation, and Other', 'FEMA Public Assistance Category G — parks, recreation, and other.'),
    ('H', 'Residential', 'FEMA Public Assistance Category H — residential.'),
    ('I', 'Commercial', 'FEMA Public Assistance Category I — commercial.')
ON CONFLICT (code) DO NOTHING;
