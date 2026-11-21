-- Slide feedback users chose to send, one table per deck style. Rows are never deleted and only two changes are
-- allowed: used_in_pr is set when a digest uses the row, and text is overwritten with '[removed]' on a redaction request.
CREATE TABLE IF NOT EXISTS consulting_feedback (
	id INTEGER PRIMARY KEY,
	created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
	slide_type TEXT,
	deck_style TEXT,
	slide_role TEXT NOT NULL,
	message TEXT NOT NULL,
	correction TEXT NOT NULL,
	reason TEXT,
	used_in_pr TEXT
);
CREATE INDEX IF NOT EXISTS consulting_feedback_created_at ON consulting_feedback (created_at);
CREATE TRIGGER IF NOT EXISTS consulting_feedback_no_delete BEFORE DELETE ON consulting_feedback
BEGIN SELECT RAISE(ABORT, 'feedback is never deleted'); END;
CREATE TRIGGER IF NOT EXISTS consulting_feedback_fixed_columns BEFORE UPDATE OF id, created_at, slide_type, deck_style ON consulting_feedback
BEGIN SELECT RAISE(ABORT, 'feedback is append-only'); END;
CREATE TRIGGER IF NOT EXISTS consulting_feedback_redact_only BEFORE UPDATE OF slide_role, message, correction, reason ON consulting_feedback
WHEN (NEW.slide_role IS NOT OLD.slide_role AND NEW.slide_role IS NOT '[removed]')
	OR (NEW.message IS NOT OLD.message AND NEW.message IS NOT '[removed]')
	OR (NEW.correction IS NOT OLD.correction AND NEW.correction IS NOT '[removed]')
	OR (NEW.reason IS NOT OLD.reason AND NEW.reason IS NOT '[removed]')
BEGIN SELECT RAISE(ABORT, 'feedback is append-only'); END;

CREATE TABLE IF NOT EXISTS stock_pitch_feedback (
	id INTEGER PRIMARY KEY,
	created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
	slide_type TEXT,
	deck_style TEXT,
	slide_role TEXT NOT NULL,
	message TEXT NOT NULL,
	correction TEXT NOT NULL,
	reason TEXT,
	used_in_pr TEXT
);
CREATE INDEX IF NOT EXISTS stock_pitch_feedback_created_at ON stock_pitch_feedback (created_at);
CREATE TRIGGER IF NOT EXISTS stock_pitch_feedback_no_delete BEFORE DELETE ON stock_pitch_feedback
BEGIN SELECT RAISE(ABORT, 'feedback is never deleted'); END;
CREATE TRIGGER IF NOT EXISTS stock_pitch_feedback_fixed_columns BEFORE UPDATE OF id, created_at, slide_type, deck_style ON stock_pitch_feedback
BEGIN SELECT RAISE(ABORT, 'feedback is append-only'); END;
CREATE TRIGGER IF NOT EXISTS stock_pitch_feedback_redact_only BEFORE UPDATE OF slide_role, message, correction, reason ON stock_pitch_feedback
WHEN (NEW.slide_role IS NOT OLD.slide_role AND NEW.slide_role IS NOT '[removed]')
	OR (NEW.message IS NOT OLD.message AND NEW.message IS NOT '[removed]')
	OR (NEW.correction IS NOT OLD.correction AND NEW.correction IS NOT '[removed]')
	OR (NEW.reason IS NOT OLD.reason AND NEW.reason IS NOT '[removed]')
BEGIN SELECT RAISE(ABORT, 'feedback is append-only'); END;
