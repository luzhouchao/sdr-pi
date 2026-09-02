import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import {
  createSearxngSearchClient,
  formatSearchEvidence,
  validateLoopbackSearchUrl,
} from "../src/web-search.mjs";

test("queries bounded local SearXNG and sanitizes public sources", async (t) => {
  const server = createServer((request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    assert.equal(url.pathname, "/search");
    assert.equal(url.searchParams.get("q"), "Spark SDR current facts");
    assert.equal(url.searchParams.get("format"), "json");
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({
      results: [
        {
          title: "Result\nOne",
          url: "https://example.com/fact",
          content: "Public\t snippet",
        },
        {
          title: "duplicate",
          url: "https://example.com/fact",
          content: "ignored",
        },
        { title: "unsafe", url: "file:///etc/passwd", content: "ignored" },
      ],
    }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const address = server.address();
  const search = createSearxngSearchClient({
    baseUrl: `http://127.0.0.1:${address.port}`,
    maxResults: 8,
    timeoutMs: 2_000,
  });

  const result = await search(" Spark\nSDR current facts ");
  assert.equal(result.query, "Spark SDR current facts");
  assert.deepEqual(result.sources, [{
    title: "Result One",
    url: "https://example.com/fact",
    snippet: "Public snippet",
  }]);
  assert.equal(result.truncated, true);
  assert.match(formatSearchEvidence(result), /untrusted evidence/u);
  assert.match(formatSearchEvidence(result), /https:\/\/example\.com\/fact/u);
});

test("rejects non-loopback search services and oversized bodies", async (t) => {
  assert.throws(
    () => validateLoopbackSearchUrl("https://search.example.com"),
    /loopback service/u,
  );
  assert.throws(
    () => validateLoopbackSearchUrl("http://192.168.1.2:8080"),
    /explicit loopback/u,
  );

  const server = createServer((_request, response) => {
    response.end("x".repeat(512 * 1024 + 1));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const address = server.address();
  const search = createSearxngSearchClient({
    baseUrl: `http://127.0.0.1:${address.port}`,
    timeoutMs: 2_000,
  });
  await assert.rejects(search("bounded"), /exceeds 524288 bytes/u);
});
