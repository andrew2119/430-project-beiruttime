-- CP B-27: exact revision snapshots and owner-scoped intent survive process restarts.
CREATE TABLE l10_options (
 brand_id uuid NOT NULL,
 kind text NOT NULL CHECK (kind IN ('color','material','dial','sophistication')),
 option_id uuid NOT NULL,
 revision integer NOT NULL CHECK (revision > 0),
 definition jsonb NOT NULL,
 created_by uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (brand_id,kind,option_id,revision)
);
CREATE INDEX l10_option_catalog ON l10_options(brand_id,kind,option_id,revision DESC);
CREATE TABLE l10_configurations (
 id uuid PRIMARY KEY,
 owner_id uuid NOT NULL,
 brand_id uuid NOT NULL,
 base_model text NOT NULL CHECK (length(base_model) BETWEEN 1 AND 80),
 caliber text NOT NULL CHECK (length(caliber) BETWEEN 1 AND 80),
 revision integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(id,owner_id)
);
CREATE INDEX l10_config_owner ON l10_configurations(owner_id,updated_at DESC);
CREATE TABLE l10_selections (
 configuration_id uuid NOT NULL REFERENCES l10_configurations(id),
 kind text NOT NULL CHECK (kind IN ('color','material','dial','sophistication')),
 component text NOT NULL,
 brand_id uuid NOT NULL,
 option_id uuid NOT NULL,
 option_revision integer NOT NULL,
 reference_ids uuid[] NOT NULL DEFAULT '{}',
 PRIMARY KEY(configuration_id,kind,component),
 FOREIGN KEY(brand_id,kind,option_id,option_revision) REFERENCES l10_options(brand_id,kind,option_id,revision)
);
CREATE TABLE l10_references (
 id uuid PRIMARY KEY,
 configuration_id uuid NOT NULL,
 owner_id uuid NOT NULL,
 content bytea NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 1048576),
 sha256 text NOT NULL CHECK (length(sha256)=64),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(configuration_id,owner_id) REFERENCES l10_configurations(id,owner_id)
);
CREATE TABLE l10_operations (
 owner_id uuid NOT NULL,
 operation_key text NOT NULL CHECK (length(operation_key) BETWEEN 8 AND 100),
 digest text NOT NULL CHECK (length(digest)=64),
 result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(owner_id,operation_key)
);
