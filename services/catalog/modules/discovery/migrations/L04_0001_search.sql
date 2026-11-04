-- Only dictionary data belongs to Discovery. Publication/stock remain Catalog's authority.
CREATE TABLE catalog_discovery_aliases_v1 (
    alias text PRIMARY KEY CHECK (length(alias) BETWEEN 1 AND 100),
    canonical text NOT NULL CHECK (length(canonical) BETWEEN 1 AND 100)
);
INSERT INTO catalog_discovery_aliases_v1(alias, canonical) VALUES
 ('رولكس', 'rolex'), ('روليكس', 'rolex'), ('اوميغا', 'omega'), ('اوميغـا', 'omega'),
 ('باتيك', 'patek'), ('فيليب', 'philippe'), ('اوديمار', 'audemars'), ('بيغيه', 'piguet'),
 ('كارتييه', 'cartier'), ('تيودور', 'tudor'), ('سيكو', 'seiko'), ('لونجين', 'longines'),
 ('بيروت', 'beirut'), ('طرابلس', 'tripoli'), ('صيدا', 'sidon'), ('زحله', 'zahle'), ('جونيه', 'jounieh');

CREATE FUNCTION catalog_discovery_normalize_v1(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
 SELECT trim(regexp_replace(regexp_replace(
   translate(lower(value), 'أإآٱىة٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', 'اااايه01234567890123456789'),
   '[ـً-ٰٟ]', '', 'g'), '\s+', ' ', 'g'))
$$;
