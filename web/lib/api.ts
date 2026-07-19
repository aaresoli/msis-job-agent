export function browserApi(path: string, init?: RequestInit) {
  return fetch(path, { ...init, credentials: "include", cache: "no-store" });
}

export function csrfToken(): string {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem("hope_csrf") ?? "";
}
