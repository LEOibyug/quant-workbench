export async function api<T = unknown>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    let detail: unknown = "请求失败";
    try {
      detail = (await response.json()).detail;
    } catch {
      /* Non-JSON server error. */
    }
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return response.json();
}
export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
