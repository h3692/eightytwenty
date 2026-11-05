-- Search results per (sha256 of normalised purpose, filters, k, stage flags, library_version): identical queries return
-- identical results even if Workers AI floats wobble. The key is a hash, so query text is never stored.
CREATE TABLE IF NOT EXISTS search_cache (key TEXT PRIMARY KEY, results TEXT NOT NULL);
