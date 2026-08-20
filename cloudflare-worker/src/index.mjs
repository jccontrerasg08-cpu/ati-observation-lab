const CAMPAIGN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const PROHIBITED_HEADERS = new Set([
  "authorization",
  "cookie",
  "proxy-authorization",
]);

function reject(status) {
  return new Response(null, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

function allowedCampaignIds(value) {
  return new Set(value.split(",").map((item) => item.trim()).filter(Boolean));
}

async function clientPseudonym(clientAddress, key) {
  const encoder = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    encoder.encode(key),
    { hash: "SHA-256", name: "HMAC" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", cryptoKey, encoder.encode(clientAddress));
  const bytes = new Uint8Array(signature);
  return "hmac-sha256:" + Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function validConfiguration(env) {
  return Boolean(
    env.ATI_ALLOWED_CAMPAIGN_IDS
      && env.ATI_CLIENT_PSEUDONYM_KEY
      && env.ATI_ORIGIN_URL
      && env.ATI_PROXY_ORIGIN_TOKEN,
  );
}

function originUrl(value, requestUrl) {
  const configured = new URL(value);
  if (configured.protocol !== "https:" || configured.search || configured.hash) {
    throw new TypeError("invalid origin URL");
  }
  configured.pathname = new URL(requestUrl).pathname;
  return configured;
}

export function createProxyHandler(fetchFn = fetch) {
  return async function handle(request, env) {
    if (!validConfiguration(env)) {
      return reject(503);
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return reject(400);
    }

    const requestUrl = new URL(request.url);
    if (requestUrl.pathname !== "/observe" || requestUrl.search || requestUrl.hash) {
      return reject(400);
    }
    for (const name of PROHIBITED_HEADERS) {
      if (request.headers.has(name)) {
        return reject(400);
      }
    }

    const marker = request.headers.get("X-ATI-Experiment-ID");
    if (marker && (!CAMPAIGN_ID.test(marker) || !allowedCampaignIds(env.ATI_ALLOWED_CAMPAIGN_IDS).has(marker))) {
      return reject(403);
    }

    const clientAddress = request.headers.get("CF-Connecting-IP");
    if (!clientAddress || clientAddress.includes(",")) {
      return reject(503);
    }

    let target;
    try {
      target = originUrl(env.ATI_ORIGIN_URL, request.url);
    } catch (error) {
      return reject(503);
    }

    const headers = new Headers();
    headers.set("X-ATI-Proxy-Token", env.ATI_PROXY_ORIGIN_TOKEN);
    headers.set(
      "X-ATI-Proxy-Client-ID",
      await clientPseudonym(clientAddress, env.ATI_CLIENT_PSEUDONYM_KEY),
    );
    headers.set("User-Agent", request.headers.get("User-Agent")?.slice(0, 512) ?? "");
    if (marker) {
      headers.set("X-ATI-Experiment-ID", marker);
    }

    return fetchFn(new Request(target, { headers, method: request.method, redirect: "manual" }));
  };
}

export default { fetch: createProxyHandler() };
