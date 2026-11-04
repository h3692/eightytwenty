// One SQLite Durable Object instance holds every per-client counter and the global daily search budget.
// Rows are deleted 24 hours after a client's last request, so IPs are never kept longer than that.
import { DurableObject } from "cloudflare:workers";

export type Limits = { perMinute: number; perMinuteShared: number; dailySearchBudget: number };
export type Verdict = { ok: boolean; message: string; retryAfter: number };

const WINDOW_MS = 60_000, MAX_COOLDOWN_MIN = 60, KEEP_MS = 86_400_000;

export class Limiter extends DurableObject<Env> {
	sql = this.ctx.storage.sql;
	pruned = 0;
	armed = false;

	constructor(ctx: DurableObjectState, env: Env) {
		super(ctx, env);
		ctx.blockConcurrencyWhile(async () => { this.armed = (await ctx.storage.getAlarm()) !== null; });
		this.sql.exec(`CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, window_start INTEGER, count INTEGER, strikes INTEGER, cooldown_until INTEGER, seen INTEGER);
			CREATE INDEX IF NOT EXISTS keys_seen ON keys (seen);
			CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY, used INTEGER)`);
	}

	// `search` = the call spends the daily budget (find_references). The shared "anthropic" key gets perMinuteShared.
	check(key: string, search: boolean, limits: Limits, now = Date.now()): Verdict {
		const day = new Date(now).toISOString().slice(0, 10);
		if (now - this.pruned >= WINDOW_MS) {
			this.sql.exec("DELETE FROM keys WHERE seen < ?", now - KEEP_MS);
			this.sql.exec("DELETE FROM budget WHERE day <> ?", day);
			this.pruned = now;
		}
		const row = this.sql.exec<{ window_start: number; count: number; strikes: number; cooldown_until: number }>(
			"SELECT window_start, count, strikes, cooldown_until FROM keys WHERE key = ?", key).toArray()[0]
			?? { window_start: now, count: 0, strikes: 0, cooldown_until: 0 };
		if (!this.armed) {
			this.armed = true;
			void this.ctx.storage.setAlarm(now + KEEP_MS); // first client since the table emptied: alarm() prunes from here on
		}
		const save = () => this.sql.exec("INSERT OR REPLACE INTO keys VALUES (?, ?, ?, ?, ?, ?)", key, row.window_start, row.count, row.strikes, row.cooldown_until, now);
		const slowDown = (until: number): Verdict => {
			const min = Math.ceil((until - now) / 60_000);
			return { ok: false, message: `Slow down: too many searches. Try again in ${min} minute${min === 1 ? "" : "s"}.`, retryAfter: min * 60 };
		};

		if (row.cooldown_until > now) return slowDown(row.cooldown_until);
		if (now - row.window_start >= WINDOW_MS) [row.window_start, row.count] = [now, 0];
		row.count++;
		if (row.count > (key === "anthropic" ? limits.perMinuteShared : limits.perMinute)) {
			row.strikes++;
			row.cooldown_until = now + Math.min(2 ** (row.strikes - 1), MAX_COOLDOWN_MIN) * 60_000; // 1, 2, 4 ... 60 min
			save();
			return slowDown(row.cooldown_until);
		}
		if (search) {
			const used = this.sql.exec<{ used: number }>("SELECT used FROM budget WHERE day = ?", day).toArray()[0]?.used ?? 0;
			if (used >= limits.dailySearchBudget) {
				save();
				const retryAfter = Math.ceil((Date.parse(day) + KEEP_MS - now) / 1000);
				return { ok: false, message: "The shared daily search budget is used up. Try again after 00:00 UTC.", retryAfter };
			}
			this.sql.exec("INSERT OR REPLACE INTO budget VALUES (?, ?)", day, used + 1);
		}
		save();
		return { ok: true, message: "ok", retryAfter: 0 };
	}

	// Deletes clients idle for 24 hours even when no request arrives, then wakes when the next one turns 24 hours old.
	async alarm() {
		this.sql.exec("DELETE FROM keys WHERE seen <= ?", Date.now() - KEEP_MS);
		const next = this.sql.exec<{ seen: number | null }>("SELECT min(seen) AS seen FROM keys").one().seen;
		this.armed = next !== null;
		if (next !== null) await this.ctx.storage.setAlarm(next + KEEP_MS);
	}
}
