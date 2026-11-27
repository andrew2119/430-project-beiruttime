CREATE TABLE movement_selection_archive (
 actor_id uuid NOT NULL,
 brand_id uuid NOT NULL,
 revision integer NOT NULL CHECK(revision>0),
 result jsonb NOT NULL,
 PRIMARY KEY(actor_id,brand_id,revision)
);
