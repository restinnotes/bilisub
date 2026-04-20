const DEFAULT_SERVER_BASE = "http://127.0.0.1:8765";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "bilisub:api-request") {
    return false;
  }

  const request = message.payload || {};
  handleApiRequest(request)
    .then((data) => sendResponse({ ok: true, data }))
    .catch((error) => {
      sendResponse({
        ok: false,
        error: error?.message || "Unknown background request error"
      });
    });

  return true;
});

async function handleApiRequest(request) {
  const baseUrl = request.baseUrl || DEFAULT_SERVER_BASE;
  const url = new URL(request.path, `${baseUrl}/`).toString();
  const response = await fetch(url, {
    method: request.method || "GET",
    headers: {
      "Content-Type": "application/json",
      ...(request.headers || {})
    },
    body: request.body ? JSON.stringify(request.body) : undefined,
    credentials: "omit"
  });

  const text = await response.text();
  let parsed;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = text;
  }

  if (!response.ok) {
    const errorMessage = parsed?.detail || parsed?.error || response.statusText;
    throw new Error(`Local server error (${response.status}): ${errorMessage}`);
  }

  return parsed;
}
