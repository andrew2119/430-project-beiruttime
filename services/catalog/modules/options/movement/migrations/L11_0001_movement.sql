CREATE TABLE movement_options (
 id uuid PRIMARY KEY,
 brand_id uuid NOT NULL,
 revision integer NOT NULL CHECK(revision>0),
 label_en text NOT NULL CHECK(length(label_en) BETWEEN 1 AND 160),
 label_ar text NOT NULL CHECK(length(label_ar) BETWEEN 1 AND 160),
 caliber text NOT NULL CHECK(length(caliber) BETWEEN 1 AND 80),
 cases text[] NOT NULL CHECK(cardinality(cases) BETWEEN 1 AND 30),
 dials text[] NOT NULL CHECK(cardinality(dials) BETWEEN 1 AND 30),
 hands text[] NOT NULL CHECK(cardinality(hands) BETWEEN 1 AND 30),
 functions text[] NOT NULL CHECK(cardinality(functions)<=20),
 quote_minor bigint NOT NULL CHECK(quote_minor BETWEEN 0 AND 999999999999),
 currency text NOT NULL CHECK(currency IN ('USD','LBP')),
 active boolean NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX movement_options_brand ON movement_options(brand_id,id) WHERE active;
CREATE TABLE movement_selections (
 actor_id uuid NOT NULL,
 brand_id uuid NOT NULL,
 id uuid NOT NULL UNIQUE,
 option_id uuid NOT NULL REFERENCES movement_options(id),
 revision integer NOT NULL CHECK(revision>0),
 option_revision integer NOT NULL CHECK(option_revision>0),
 configuration jsonb NOT NULL,
 result jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(actor_id,brand_id)
);
CREATE TABLE movement_commands (
 actor_id uuid NOT NULL,
 command text NOT NULL,
 key text NOT NULL CHECK(length(key) BETWEEN 8 AND 100),
 digest text NOT NULL CHECK(length(digest)=64),
 result jsonb NOT NULL,
 PRIMARY KEY(actor_id,command,key)
);
