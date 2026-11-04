-- Match either Arabic or Latin source text, not just Arabic query input.
CREATE FUNCTION catalog_discovery_canonicalize_v1(value text) RETURNS text
LANGUAGE sql STABLE STRICT PARALLEL SAFE AS $$
 SELECT coalesce(string_agg(coalesce(aliases.canonical, words.word), ' ' ORDER BY words.ordinality), '')
 FROM regexp_split_to_table(catalog_discovery_normalize_v1(value), ' ') WITH ORDINALITY AS words(word, ordinality)
 LEFT JOIN catalog_discovery_aliases_v1 AS aliases ON aliases.alias=words.word
$$;
