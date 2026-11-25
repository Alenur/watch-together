export class ApiError extends Error {
  constructor(status, code, detail) {
    super(detail);
    this.status = status;
    this.code = code;
  }
}

export async function api(path, method = 'GET', data) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      cache: 'no-store',
      ...(data === undefined ? {} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)}),
    });
  } catch {
    throw new ApiError(0, 'offline', 'Связь с сервером потеряна. Попробуйте ещё раз.');
  }
  if (response.status === 204) return;
  const result = await response.json().catch(() => null);
  if (!response.ok || result === null) {
    throw new ApiError(response.status, result?.code, result?.detail || 'Сервер временно недоступен. Попробуйте ещё раз.');
  }
  return result;
}
