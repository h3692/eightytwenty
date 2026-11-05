// POST {"text": [...]} -> bge-m3 embeddings via the Workers AI binding. Local dev only.
const MODEL = "@cf/baai/bge-m3";

export default {
  async fetch(request, env) {
    const host = new URL(request.url).hostname;
    if (host !== "localhost" && host !== "127.0.0.1") return new Response("local only", { status: 403 });
    if (request.method !== "POST") return new Response('POST {"text": [...]}', { status: 405 });
    const { text } = await request.json();
    const out = await env.AI.run(MODEL, { text });
    return Response.json({ model: MODEL, pooling: out.pooling, shape: out.shape, data: out.data });
  },
};
