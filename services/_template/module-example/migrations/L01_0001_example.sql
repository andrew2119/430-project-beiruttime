-- Rename this migration and module id to the owning lane before copying.
CREATE TABLE example_record (id uuid PRIMARY KEY, revision integer NOT NULL CHECK(revision >= 1));
