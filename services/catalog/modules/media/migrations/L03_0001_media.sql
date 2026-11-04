CREATE TABLE catalog_media (
 id uuid PRIMARY KEY,
 listing_id uuid NOT NULL REFERENCES catalog_listings(id),
 kind text NOT NULL CHECK(kind IN ('public_photo','private_document')),
 content_hash text NOT NULL,
 source_bytes integer NOT NULL CHECK(source_bytes BETWEEN 1 AND 8000000),
 mime text NOT NULL,
 width integer,
 height integer,
 credit jsonb,
 private_bytes bytea,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((kind='private_document' AND private_bytes IS NOT NULL) OR (kind='public_photo' AND private_bytes IS NULL))
);
CREATE INDEX catalog_media_listing ON catalog_media(listing_id,kind,id);
CREATE TABLE catalog_media_variants (
 media_id uuid NOT NULL REFERENCES catalog_media(id) ON DELETE CASCADE,
 variant text NOT NULL CHECK (variant IN ('thumb','card','detail')),
 width integer NOT NULL CHECK(width BETWEEN 1 AND 1600),
 height integer NOT NULL CHECK(height BETWEEN 1 AND 1600),
 content bytea NOT NULL,
 PRIMARY KEY(media_id,variant)
);
