import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

const tables = ["consulting_feedback", "stock_pitch_feedback"];
const insert = (table: string) =>
	env.FEEDBACK.prepare(`INSERT INTO ${table} (slide_type, deck_style, slide_role, message, correction, reason) VALUES (?, ?, ?, ?, ?, ?) RETURNING id`)
		.bind("chart", "consulting", "evidence", "the chart buries the claim", "lead with the claim", "readers skim titles")
		.first<{ id: number }>();

describe.each(tables)("%s", (table) => {
	it("stores rows in each feedback table", async () => {
		const { id } = (await insert(table))!;
		const row = await env.FEEDBACK.prepare(`SELECT * FROM ${table} WHERE id = ?`).bind(id).first<Record<string, unknown>>();
		expect(row).toMatchObject({ slide_type: "chart", deck_style: "consulting", slide_role: "evidence", message: "the chart buries the claim", correction: "lead with the claim", reason: "readers skim titles", used_in_pr: null });
		expect(row!.created_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
	});

	it("refuses to delete feedback", async () => {
		const { id } = (await insert(table))!;
		await expect(env.FEEDBACK.prepare(`DELETE FROM ${table} WHERE id = ?`).bind(id).run()).rejects.toThrow(/feedback is never deleted/);
		expect(await env.FEEDBACK.prepare(`SELECT id FROM ${table} WHERE id = ?`).bind(id).first()).not.toBeNull();
	});

	it("allows marking used_in_pr and redacting text to [removed], nothing else", async () => {
		const { id } = (await insert(table))!;
		const set = (sql: string) => env.FEEDBACK.prepare(`UPDATE ${table} SET ${sql} WHERE id = ?`).bind(id).run();

		await set("used_in_pr = 'https://github.com/x/y/pull/1'");
		await set("message = '[removed]', correction = '[removed]', reason = '[removed]', slide_role = '[removed]'");

		for (const sql of ["id = 999", "created_at = '2000-01-01T00:00:00Z'", "slide_type = 'table'", "deck_style = 'pitch'", "message = 'rewritten'", "slide_role = 'other'", "reason = NULL"])
			await expect(set(sql), sql).rejects.toThrow(/feedback is append-only/);

		expect(await env.FEEDBACK.prepare(`SELECT * FROM ${table} WHERE id = ?`).bind(id).first()).toMatchObject({ id, slide_type: "chart", deck_style: "consulting", slide_role: "[removed]", message: "[removed]", correction: "[removed]", reason: "[removed]", used_in_pr: "https://github.com/x/y/pull/1" });
	});
});
