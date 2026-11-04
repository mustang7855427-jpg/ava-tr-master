export async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });
  const data = response.status === 204 ? {} : await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Błąd serwera (${response.status}).`);
  }
  return data;
}

export function postJson(path, data) {
  return api(path, { method: "POST", body: JSON.stringify(data) });
}
