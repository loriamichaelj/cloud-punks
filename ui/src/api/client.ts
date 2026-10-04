// The only place that calls fetch. Same-origin, relative URLs (the gateway serves both the SPA
// and /api/v1), every request carries X-Correlation-ID, and every failure becomes one of two
// error types so the screens can tell "the API said no" from "the network is gone".

import { CORRELATION_HEADER, newCorrelationId } from '../lib/correlation';

export const API_PREFIX = '/api/v1';

/** The API answered with an error (the shared shape {error: {code, message, correlation_id}}). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string | null;
  readonly retryAfterS: number | null;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    correlationId: string | null;
    retryAfterS?: number | null;
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.status = init.status;
    this.code = init.code;
    this.correlationId = init.correlationId;
    this.retryAfterS = init.retryAfterS ?? null;
  }
}

/** No answer at all: the gateway is unreachable, the connection dropped or the request timed out. */
export class NetworkError extends Error {
  readonly correlationId: string;

  constructor(correlationId: string) {
    super('Could not reach the server.');
    this.name = 'NetworkError';
    this.correlationId = correlationId;
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  /** One id per user action; generated when the caller does not pass one. */
  correlationId?: string;
  signal?: AbortSignal;
  /** Automatic retries of a 503 (with Retry-After). Only safe for idempotent requests. */
  retry503?: number;
  /** Test seam: how to wait between retries. */
  sleep?: (ms: number) => Promise<void>;
}

const MAX_RETRY_WAIT_S = 5;
const DEFAULT_RETRY_WAIT_S = 1;

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

async function toApiError(response: Response, fallbackCorrelationId: string): Promise<ApiError> {
  let code = 'UNKNOWN_ERROR';
  let message = `The server answered ${response.status}.`;
  let correlationId: string | null = response.headers.get(CORRELATION_HEADER);
  try {
    const body = (await response.json()) as { error?: Record<string, unknown> } | null;
    const error = body?.error;
    if (error) {
      code = asString(error.code) ?? code;
      message = asString(error.message) ?? message;
      correlationId = asString(error.correlation_id) ?? correlationId;
    }
  } catch {
    // not the shared error shape (an HTML error page from a proxy, say): keep the generic text
  }
  const retryAfter = Number(response.headers.get('Retry-After'));
  return new ApiError({
    status: response.status,
    code,
    message,
    correlationId: correlationId ?? fallbackCorrelationId,
    retryAfterS: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
  });
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const correlationId = options.correlationId ?? newCorrelationId();
  const sleep = options.sleep ?? defaultSleep;
  const init: RequestInit = {
    method: options.method ?? 'GET',
    headers: {
      Accept: 'application/json',
      ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
      [CORRELATION_HEADER]: correlationId,
    },
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
    ...(options.signal ? { signal: options.signal } : {}),
  };

  for (let attempt = 0; ; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(`${API_PREFIX}${path}`, init);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
      throw new NetworkError(correlationId);
    }
    if (response.ok) return (await response.json()) as T;

    const error = await toApiError(response, correlationId);
    if (error.status === 503 && attempt < (options.retry503 ?? 0)) {
      const waitS = Math.min(error.retryAfterS ?? DEFAULT_RETRY_WAIT_S, MAX_RETRY_WAIT_S);
      await sleep(waitS * 1000);
      continue;
    }
    throw error;
  }
}
