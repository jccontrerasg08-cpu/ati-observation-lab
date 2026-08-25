import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import test from "node:test";

import { createProxyHandler } from "../src/index.mjs";

const execFileAsync = promisify(execFile);

const ENV = {
  ATI_ALLOWED_CAMPAIGN_IDS: "owned-shadow-2026-08-20-a",
  ATI_CLIENT_PSEUDONYM_KEY: "test-pseudonym-key",
  ATI_ORIGIN_URL: "https://ati-observation-lab-production.up.railway.app",
  ATI_PROXY_ORIGIN_TOKEN: "test-origin-token",
  ATI_SESSION_SIGNING_KEY: "test-session-signing-key",
};

function proxyWithFetch() {
  const requests = [];
  const fetchFn = async (request) => {
    requests.push(request);
    return new Response('{"status":"observed"}', {
      headers: { "Cache-Control": "no-store", "Content-Type": "application/json" },
    });
  };
  return { handler: createProxyHandler(fetchFn), requests };
}

test("has no unsupported Wrangler configuration fields", async () => {
  const { stderr, stdout } = await execFileAsync(
    "npx",
    [
      "--yes",
      "wrangler@4.42.1",
      "deploy",
      "--dry-run",
      "--config",
      "cloudflare-worker/wrangler.jsonc",
    ],
    { cwd: new URL("../..", import.meta.url).pathname },
  );

  assert.doesNotMatch(`${stdout}${stderr}`, /Unexpected fields found/);
});

test("enables the Workers.dev fallback when no custom domain is configured", async () => {
  const configuration = await readFile(new URL("../wrangler.jsonc", import.meta.url), "utf8");

  assert.doesNotMatch(configuration, /"workers_dev"\s*:\s*false/);
});

test("declares only the approved custom-domain campaign markers", async () => {
  const configuration = JSON.parse(
    await readFile(new URL("../wrangler.jsonc", import.meta.url), "utf8"),
  );

  assert.deepEqual(configuration.vars, {
    ATI_ALLOWED_CAMPAIGN_IDS: [
      "owned-domain-2026-08-22-curl",
      "owned-domain-2026-08-22-wget",
      "owned-domain-2026-08-22-requests",
      "owned-domain-2026-08-22-httpx",
      "owned-domain-2026-08-22-node-fetch",
      "owned-domain-2026-08-22-playwright-chromium",
      "owned-domain-2026-08-22-human-consented",
      "owned-domain-2026-08-22-external-cloud-a",
      "owned-domain-2026-08-22-external-cloud-b",
      "owned-domain-2026-08-25-pf2-curl",
      "owned-domain-2026-08-25-pf2-wget",
      "owned-domain-2026-08-25-pf2-requests",
      "owned-domain-2026-08-25-pf2-httpx",
      "owned-domain-2026-08-25-pf2-node-fetch",
      "owned-domain-2026-08-25-pf2-playwright-chromium",
      "owned-domain-2026-08-25-pf2-human-consented",
    ].join(","),
    ATI_ORIGIN_URL: "https://ati-observation-lab-production.up.railway.app",
  });
});

test("forwards only the allowlisted context with edge-derived pseudonym", async () => {
  const { handler, requests } = proxyWithFetch();

  const response = await handler(
    new Request("https://observe.example/observe", {
      headers: {
        Accept: "application/json",
        "CF-Connecting-IP": "198.51.100.7",
        Cookie: "must-be-rejected",
        "User-Agent": "ControlledAgent/1.0",
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a",
        "X-Forwarded-For": "203.0.113.4",
      },
    }),
    ENV,
  );

  assert.equal(response.status, 400);
  assert.equal(requests.length, 0);
});

test("replaces client-supplied proxy credentials with private origin context", async () => {
  const { handler, requests } = proxyWithFetch();

  const response = await handler(
    new Request("https://observe.example/observe", {
      headers: {
        "CF-Connecting-IP": "198.51.100.7",
        "User-Agent": "ControlledAgent/1.0",
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a",
        "X-ATI-Proxy-Client-ID": "hmac-sha256:" + "b".repeat(64),
        "X-ATI-Proxy-Token": "attacker-token",
      },
    }),
    ENV,
  );

  assert.equal(response.status, 200);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "https://ati-observation-lab-production.up.railway.app/observe");
  assert.equal(requests[0].headers.get("X-ATI-Proxy-Token"), "test-origin-token");
  assert.match(requests[0].headers.get("X-ATI-Proxy-Client-ID"), /^hmac-sha256:[0-9a-f]{64}$/);
  assert.notEqual(
    requests[0].headers.get("X-ATI-Proxy-Client-ID"),
    "hmac-sha256:" + "b".repeat(64),
  );
  assert.equal(requests[0].headers.get("CF-Connecting-IP"), null);
  assert.equal(requests[0].headers.get("X-Forwarded-For"), null);
});

test("does not change the pseudonym when a client spoofs X-Forwarded-For", async () => {
  const { handler, requests } = proxyWithFetch();
  const baseHeaders = {
    "CF-Connecting-IP": "198.51.100.7",
    "User-Agent": "ControlledAgent/1.0",
  };

  await handler(
    new Request("https://observe.example/observe", {
      headers: { ...baseHeaders, "X-Forwarded-For": "203.0.113.4" },
    }),
    ENV,
  );
  await handler(
    new Request("https://observe.example/observe", {
      headers: { ...baseHeaders, "X-Forwarded-For": "192.0.2.5" },
    }),
    ENV,
  );

  assert.equal(requests.length, 2);
  assert.equal(
    requests[0].headers.get("X-ATI-Proxy-Client-ID"),
    requests[1].headers.get("X-ATI-Proxy-Client-ID"),
  );
});

test("rejects methods, query strings, bodies, and sensitive headers without forwarding", async () => {
  const cases = [
    new Request("https://observe.example/observe", {
      method: "POST",
      body: "not allowed",
      headers: { "CF-Connecting-IP": "198.51.100.7" },
    }),
    new Request("https://observe.example/observe?email=private@example.com", {
      headers: { "CF-Connecting-IP": "198.51.100.7" },
    }),
    new Request("https://observe.example/observe", {
      headers: {
        Authorization: "Bearer never-forward",
        "CF-Connecting-IP": "198.51.100.7",
      },
    }),
  ];

  for (const request of cases) {
    const { handler, requests } = proxyWithFetch();
    const response = await handler(request, ENV);
    assert.equal(response.status, 400);
    assert.equal(requests.length, 0);
  }
});

test("rejects a non-allowlisted campaign marker without forwarding", async () => {
  const { handler, requests } = proxyWithFetch();

  const response = await handler(
    new Request("https://observe.example/observe", {
      headers: {
        "CF-Connecting-IP": "198.51.100.7",
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-b",
      },
    }),
    ENV,
  );

  assert.equal(response.status, 403);
  assert.equal(requests.length, 0);
});


test("issues an opaque lab session and forwards only its derived identifier", async () => {
  const { handler, requests } = proxyWithFetch();

  const start = await handler(
    new Request("https://observe.example/lab/start", {
      headers: {
        "CF-Connecting-IP": "198.51.100.7",
        "User-Agent": "ControlledBrowser/1.0",
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a",
      },
    }),
    ENV,
  );

  assert.equal(start.status, 200);
  const session = start.headers.get("X-ATI-Lab-Session");
  assert.match(session, /^ati1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "https://ati-observation-lab-production.up.railway.app/lab/start");
  assert.match(requests[0].headers.get("X-ATI-Proxy-Session-ID"), /^hmac-sha256:[0-9a-f]{64}$/);
  assert.equal(requests[0].headers.get("X-ATI-Lab-Session"), null);

  const page = await handler(
    new Request("https://observe.example/lab/page/landing", {
      headers: {
        "CF-Connecting-IP": "198.51.100.7",
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a",
        "X-ATI-Lab-Session": session,
      },
    }),
    ENV,
  );

  assert.equal(page.status, 200);
  assert.equal(requests.length, 2);
  assert.equal(requests[1].url, "https://ati-observation-lab-production.up.railway.app/lab/page/landing");
  assert.equal(
    requests[1].headers.get("X-ATI-Proxy-Session-ID"),
    requests[0].headers.get("X-ATI-Proxy-Session-ID"),
  );
  assert.equal(requests[1].headers.get("X-ATI-Lab-Session"), null);
});


test("rejects invalid lab sessions and cookies before forwarding", async () => {
  const cases = [
    new Request("https://observe.example/lab/page/landing", {
      headers: { "CF-Connecting-IP": "198.51.100.7" },
    }),
    new Request("https://observe.example/lab/page/landing", {
      headers: {
        "CF-Connecting-IP": "198.51.100.7",
        "X-ATI-Lab-Session": "ati1.invalid.signature",
      },
    }),
    new Request("https://observe.example/lab/start", {
      headers: { "CF-Connecting-IP": "198.51.100.7", Cookie: "must-not-pass" },
    }),
  ];

  for (const request of cases) {
    const { handler, requests } = proxyWithFetch();
    const response = await handler(request, ENV);
    assert.equal(response.status, request.headers.has("Cookie") ? 400 : 403);
    assert.equal(requests.length, 0);
  }
});


test("uses a campaign scope when Workers.dev has no edge client IP", async () => {
  const { handler, requests } = proxyWithFetch();

  const response = await handler(
    new Request("https://observe.example/observe", {
      headers: { "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a" },
    }),
    ENV,
  );

  assert.equal(response.status, 200);
  assert.equal(requests.length, 1);
  assert.match(requests[0].headers.get("X-ATI-Proxy-Client-ID"), /^hmac-sha256:[0-9a-f]{64}$/);
});

test("derives the same campaign scope despite client-supplied CF-Connecting-IP", async () => {
  const { handler, requests } = proxyWithFetch();
  const headers = { "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a" };

  await handler(
    new Request("https://observe.example/observe", {
      headers: { ...headers, "CF-Connecting-IP": "198.51.100.7" },
    }),
    ENV,
  );
  await handler(
    new Request("https://observe.example/observe", {
      headers: { ...headers, "CF-Connecting-IP": "203.0.113.9" },
    }),
    ENV,
  );

  assert.equal(requests.length, 2);
  assert.equal(
    requests[0].headers.get("X-ATI-Proxy-Client-ID"),
    requests[1].headers.get("X-ATI-Proxy-Client-ID"),
  );
});

test("derives a client pseudonym from the edge address only on the protected custom domain", async () => {
  const { handler, requests } = proxyWithFetch();
  const marker = "owned-shadow-2026-08-20-a";

  async function forwardClientId(url, address) {
    const response = await handler(
      new Request(url, {
        headers: {
          "CF-Connecting-IP": address,
          "X-ATI-Experiment-ID": marker,
          "X-Forwarded-For": "203.0.113.4",
        },
      }),
      ENV,
    );
    assert.equal(response.status, 200);
    return requests.at(-1).headers.get("X-ATI-Proxy-Client-ID");
  }

  const protectedFirst = await forwardClientId(
    "https://observe.ati-observation-lab.com/observe",
    "198.51.100.7",
  );
  const protectedSecond = await forwardClientId(
    "https://observe.ati-observation-lab.com/observe",
    "203.0.113.9",
  );
  const workersDevFirst = await forwardClientId(
    "https://ati-observation-proxy.jccontrerasg08.workers.dev/observe",
    "198.51.100.7",
  );
  const workersDevSecond = await forwardClientId(
    "https://ati-observation-proxy.jccontrerasg08.workers.dev/observe",
    "203.0.113.9",
  );
  const untrustedFirst = await forwardClientId("https://observe.example/observe", "198.51.100.7");
  const untrustedSecond = await forwardClientId("https://observe.example/observe", "203.0.113.9");

  assert.notEqual(protectedFirst, protectedSecond);
  assert.equal(workersDevFirst, workersDevSecond);
  assert.equal(untrustedFirst, untrustedSecond);
  assert.equal(workersDevFirst, untrustedFirst);
  for (const forwarded of requests) {
    assert.equal(forwarded.headers.get("CF-Connecting-IP"), null);
    assert.equal(forwarded.headers.get("X-Forwarded-For"), null);
  }
});

test("binds each lab session to the campaign that issued it", async () => {
  const { handler, requests } = proxyWithFetch();
  const env = {
    ...ENV,
    ATI_ALLOWED_CAMPAIGN_IDS: "owned-shadow-2026-08-20-a,owned-shadow-2026-08-20-b",
  };

  const start = await handler(
    new Request("https://observe.example/lab/start", {
      headers: { "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a" },
    }),
    env,
  );
  const session = start.headers.get("X-ATI-Lab-Session");
  const page = await handler(
    new Request("https://observe.example/lab/page/landing", {
      headers: {
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-b",
        "X-ATI-Lab-Session": session,
      },
    }),
    env,
  );

  assert.equal(start.status, 200);
  assert.equal(page.status, 403);
  assert.equal(requests.length, 1);
});


test("documents the custom-domain client pseudonym in the repository privacy contract", async () => {
  const guide = await readFile(new URL("../../README.md", import.meta.url), "utf8");

  assert.match(guide, /`observe\.ati-observation-lab\.com`/);
  assert.match(guide, /edge client address/);
  assert.match(guide, /campaign scope on Workers\.dev/);
  assert.match(guide, /per-pseudonym limit/);
});

test("documents Workers.dev campaign scopes instead of IP-derived client identity", async () => {
  const guide = await readFile(new URL("../README.md", import.meta.url), "utf8");

  assert.match(guide, /does not derive or claim a visitor identity from IP-address headers/);
  assert.match(guide, /Only on `observe\.ati-observation-lab\.com`/);
  assert.doesNotMatch(guide, /reads `CF-Connecting-IP`/);
});


test("forwards ATI-PF-2 branch and completion paths only with an issued lab session", async () => {
  const { handler, requests } = proxyWithFetch();
  const start = await handler(
    new Request("https://observe.example/lab/start", {
      headers: { "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a" },
    }),
    ENV,
  );
  const session = start.headers.get("X-ATI-Lab-Session");
  assert.match(session, /^ati1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);

  const related = await handler(
    new Request("https://observe.example/lab/page/related", {
      headers: {
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a",
        "X-ATI-Lab-Session": session,
      },
    }),
    ENV,
  );
  const complete = await handler(
    new Request("https://observe.example/lab/complete", {
      headers: {
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a",
        "X-ATI-Lab-Session": session,
      },
    }),
    ENV,
  );

  assert.equal(related.status, 200);
  assert.equal(complete.status, 200);
  assert.equal(requests.length, 3);
  assert.equal(requests[1].url, "https://ati-observation-lab-production.up.railway.app/lab/page/related");
  assert.equal(requests[2].url, "https://ati-observation-lab-production.up.railway.app/lab/complete");
  assert.equal(
    requests[1].headers.get("X-ATI-Proxy-Session-ID"),
    requests[2].headers.get("X-ATI-Proxy-Session-ID"),
  );
});


test("forwards coarse User-Agent provenance without the raw header", async () => {
  const { handler, requests } = proxyWithFetch();

  const response = await handler(
    new Request("https://observe.example/observe", {
      headers: {
        "User-Agent": "curl/8.0.1 ControlledAuditValue/9.9",
        "X-ATI-Experiment-ID": "owned-shadow-2026-08-20-a",
      },
    }),
    ENV,
  );

  assert.equal(response.status, 200);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].headers.get("User-Agent"), null);
  assert.equal(
    requests[0].headers.get("X-ATI-UA-Provenance-Bucket"),
    "scripted-http",
  );
});
