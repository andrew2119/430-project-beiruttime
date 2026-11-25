CREATE TABLE identity_possession_retention (
 photo_id uuid PRIMARY KEY REFERENCES identity_l19_possession_photos(id) ON DELETE CASCADE,
 revision bigint NOT NULL CHECK(revision>0),
 sha256 text NOT NULL,
 expires_at timestamptz NOT NULL
);
