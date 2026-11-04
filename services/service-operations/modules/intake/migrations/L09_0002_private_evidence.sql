CREATE TABLE technical_intake_evidence (
 id uuid PRIMARY KEY, record_id uuid NOT NULL REFERENCES technical_intakes(id),
 organization_id uuid NOT NULL, kind text NOT NULL CHECK(kind IN ('condition_photo','prior_owner_record')),
 media_type text NOT NULL CHECK(media_type IN ('image/jpeg','image/png','image/webp','application/pdf')),
 content bytea NOT NULL CHECK(octet_length(content) BETWEEN 1 AND 262144),
 sha256 text NOT NULL CHECK(length(sha256)=64), author_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(record_id,kind,sha256)
);
CREATE INDEX technical_intake_evidence_scope ON technical_intake_evidence(record_id,organization_id,created_at);
