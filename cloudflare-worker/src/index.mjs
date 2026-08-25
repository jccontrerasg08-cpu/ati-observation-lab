const CAMPAIGN_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const PROHIBITED_HEADERS = new Set([
  "authorization",
  "cookie",
  "proxy-authorization",
]);
const LAB_PATHS = new Set([
  "/lab/start",
  "/lab/page/landing",
  "/lab/page/catalog",
  "/lab/page/detail",
  "/lab/page/related",
  "/lab/complete",
  "/lab/assets/site.css",
  "/lab/assets/pixel.svg",
  "/lab/missing",
]);
const SESSION_TTL_SECONDS = 15 * 60;
const TRUSTED_CUSTOM_DOMAIN = "observe.ati-observation-lab.com";
const SCRIPTED_USER_AGENT_MARKERS = [
  "aiohttp",
  "curl",
  "go-http-client",
  "httpx",
  "node-fetch",
  "python-requests",
  "undici",
  "wget",
];
const encoder = new TextEncoder();
const decoder = new TextDecoder();

function reject(status) {
  return new Response(null, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

function allowedCampaignIds(value) {
  return new Set(value.split(",").map((item) => item.trim()).filter(Boolean));
}

function uaProvenanceBucket(value) {
  const normalized = value.toLowerCase();
  if (!normalized) {
    return "absent";
  }
  if (SCRIPTED_USER_AGENT_MARKERS.some((marker) => normalized.includes(marker))) {
    return "scripted-http";
  }
  if (["mozilla/", "chrome/", "edg/", "firefox/", "safari/"].some((marker) => normalized.includes(marker))) {
    return "browser-like";
  }
  return "other";
}

function base64UrlEncode(bytes) {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function base64UrlDecode(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new TypeError("invalid base64url value");
  }
  const padded = value.replaceAll("-", "+").replaceAll("_", "/") + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function hmacKey(key, usages) {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(key),
    { hash: "SHA-256", name: "HMAC" },
    false,
    usages,
  );
}

async function hmac(value, key) {
  const cryptoKey = await hmacKey(key, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", cryptoKey, encoder.encode(value)));
}

async function clientPseudonym(clientAddress, key) {
  return "hmac-sha256:" + Array.from(await hmac(clientAddress, key), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function issueLabSession(key, campaign, now = Date.now()) {
  const nonce = new Uint8Array(16);
  crypto.getRandomValues(nonce);
  const payload = base64UrlEncode(
    encoder.encode(
      JSON.stringify({ c: campaign, e: Math.floor(now / 1000) + SESSION_TTL_SECONDS, n: base64UrlEncode(nonce) }),
    ),
  );
  const signature = base64UrlEncode(await hmac(`ati-session-v1.${payload}`, key));
  return `ati1.${payload}.${signature}`;
}

async function sessionPseudonym(token, key) {
  return clientPseudonym(`ati-session-id-v1:${token}`, key);
}

async function validLabSession(token, key, campaign, now = Date.now()) {
  const parts = token?.split(".");
  if (parts?.length !== 3 || parts[0] !== "ati1") {
    return false;
  }
  try {
    const payload = base64UrlDecode(parts[1]);
    const signature = base64UrlDecode(parts[2]);
    const cryptoKey = await hmacKey(key, ["verify"]);
    const verified = await crypto.subtle.verify(
      "HMAC",
      cryptoKey,
      signature,
      encoder.encode(`ati-session-v1.${parts[1]}`),
    );
    if (!verified) {
      return false;
    }
    const decoded = JSON.parse(decoder.decode(payload));
    return (
      decoded.c === campaign
      && Number.isSafeInteger(decoded.e)
      && decoded.e > Math.floor(now / 1000)
    );
  } catch {
    return false;
  }
}

function validConfiguration(env) {
  return Boolean(
    env.ATI_ALLOWED_CAMPAIGN_IDS
      && env.ATI_CLIENT_PSEUDONYM_KEY
      && env.ATI_ORIGIN_URL
      && env.ATI_PROXY_ORIGIN_TOKEN
      && env.ATI_SESSION_SIGNING_KEY,
  );
}

function clientIdentityScope(request, requestUrl, marker) {
  const edgeAddress = requestUrl.hostname === TRUSTED_CUSTOM_DOMAIN
    ? request.headers.get("CF-Connecting-IP")
    : null;
  return edgeAddress
    ? `ati-edge-address-v1:${edgeAddress}`
    : marker
      ? `ati-campaign-scope-v1:${marker}`
      : "ati-unmarked-scope-v1";
}

function originUrl(value, requestUrl) {
  const configured = new URL(value);
  if (configured.protocol !== "https:" || configured.search || configured.hash) {
    throw new TypeError("invalid origin URL");
  }
  configured.pathname = new URL(requestUrl).pathname;
  return configured;
}

function withSessionHeader(response, token) {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", "no-store");
  headers.set("X-ATI-Lab-Session", token);
  return new Response(response.body, {
    headers,
    status: response.status,
    statusText: response.statusText,
  });
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
    const isLabPath = requestUrl.pathname.startsWith("/lab/");
    if (
      (requestUrl.pathname !== "/observe" && !LAB_PATHS.has(requestUrl.pathname))
      || requestUrl.search
      || requestUrl.hash
    ) {
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

    let target;
    try {
      target = originUrl(env.ATI_ORIGIN_URL, request.url);
    } catch {
      return reject(503);
    }

    let sessionToken;
    let proxySessionId;
    if (isLabPath) {
      if (!marker) {
        return reject(403);
      }
      if (requestUrl.pathname === "/lab/start") {
        if (request.headers.has("X-ATI-Lab-Session")) {
          return reject(403);
        }
        sessionToken = await issueLabSession(env.ATI_SESSION_SIGNING_KEY, marker);
      } else {
        sessionToken = request.headers.get("X-ATI-Lab-Session");
        if (!(await validLabSession(sessionToken, env.ATI_SESSION_SIGNING_KEY, marker))) {
          return reject(403);
        }
      }
      proxySessionId = await sessionPseudonym(sessionToken, env.ATI_SESSION_SIGNING_KEY);
    }

    const headers = new Headers();
    headers.set("X-ATI-Proxy-Token", env.ATI_PROXY_ORIGIN_TOKEN);
    headers.set(
      "X-ATI-Proxy-Client-ID",
      await clientPseudonym(
        clientIdentityScope(request, requestUrl, marker),
        env.ATI_CLIENT_PSEUDONYM_KEY,
      ),
    );
    headers.set(
      "X-ATI-UA-Provenance-Bucket",
      uaProvenanceBucket(request.headers.get("User-Agent") ?? ""),
    );
    if (proxySessionId) {
      headers.set("X-ATI-Proxy-Session-ID", proxySessionId);
    }
    if (marker) {
      headers.set("X-ATI-Experiment-ID", marker);
    }

    const response = await fetchFn(new Request(target, { headers, method: request.method, redirect: "manual" }));
    return sessionToken && requestUrl.pathname === "/lab/start"
      ? withSessionHeader(response, sessionToken)
      : response;
  };
}

export default { fetch: createProxyHandler() };
