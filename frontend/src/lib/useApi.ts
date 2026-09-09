"use client";

import { useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch, ApiError } from "./api";

/**
 * A version of apiFetch bound to the current session's token — auto-logs-out on a
 * 401 (expired/invalid token) rather than making every page handle that itself.
 */
export function useApi() {
  const { token, logout } = useAuth();

  return useCallback(
    async function call<T>(
      path: string,
      options: { method?: string; body?: unknown } = {},
    ): Promise<T> {
      try {
        return await apiFetch<T>(path, { ...options, token });
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) logout();
        throw err;
      }
    },
    [token, logout],
  );
}
