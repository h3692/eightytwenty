-- Lets the daily cron drop cached results of older library builds (rows without a version are dropped too).
ALTER TABLE search_cache ADD COLUMN library_version TEXT;
