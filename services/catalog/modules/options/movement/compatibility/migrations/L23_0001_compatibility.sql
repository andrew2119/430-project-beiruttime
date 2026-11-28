ALTER TABLE movement_options ADD COLUMN compatibility_rules jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(compatibility_rules) = 'array');
