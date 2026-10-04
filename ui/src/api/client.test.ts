import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { apiError } from '../test/fixtures';
import { server } from '../test/server';
import { ApiError, NetworkError, request } from './client';

describe('request', () => {
  it('sends the correlation id on every request', async () => {
    let seen: string | null = null;
    server.use(
      http.get('*/api/v1/ping', ({ request: r }) => {
        seen = r.headers.get('x-correlation-id');
        return HttpResponse.json({ ok: true });
      }),
    );
    await request('/ping', { correlationId: 'corr-123' });
    expect(seen).toBe('corr-123');
    await request('/ping');
    expect(seen).toMatch(/^[A-Za-z0-9-]{16,64}$/);
  });

  it('maps the shared error shape to an ApiError', async () => {
    server.use(
      http.get('*/api/v1/x', () =>
        HttpResponse.json(apiError('OUT_OF_STOCK', 'SKU-A: requested 5, available 1', 'c-9'), {
          status: 409,
        }),
      ),
    );
    const error = await request('/x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      code: 'OUT_OF_STOCK',
      message: 'SKU-A: requested 5, available 1',
      correlationId: 'c-9',
    });
  });

  it('survives an error body that is not the shared shape (and never shows its text)', async () => {
    server.use(
      http.get(
        '*/api/v1/x',
        () => new HttpResponse('<html>Bad gateway at 10.0.0.5</html>', { status: 502 }),
      ),
    );
    const error = (await request('/x', { correlationId: 'mine' }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).not.toContain('10.0.0.5');
    expect(error.correlationId).toBe('mine');
  });

  it('reports a 200 that is not JSON (an API path routed to the SPA) as an ApiError', async () => {
    server.use(
      http.get(
        '*/api/v1/x',
        () =>
          new HttpResponse('<!doctype html><title>CloudPunks</title>', {
            status: 200,
            headers: { 'Content-Type': 'text/html' },
          }),
      ),
    );
    const error = (await request('/x', { correlationId: 'html-1' }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: 'BAD_RESPONSE', correlationId: 'html-1' });
    expect(error.message).not.toContain('doctype');
  });

  it('reports an unreachable server as a NetworkError, not an ApiError', async () => {
    server.use(http.get('*/api/v1/x', () => HttpResponse.error()));
    const error = await request('/x', { correlationId: 'net-1' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(NetworkError);
    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as NetworkError).correlationId).toBe('net-1');
  });

  describe('503 retries', () => {
    const unavailable = () =>
      HttpResponse.json(apiError('STORE_UNAVAILABLE', 'try later'), {
        status: 503,
        headers: { 'Retry-After': '2' },
      });

    it('retries a 503 at most 3 times, honouring Retry-After, then gives up', async () => {
      let calls = 0;
      server.use(
        http.post('*/api/v1/orders', () => {
          calls += 1;
          return unavailable();
        }),
      );
      const sleep = vi.fn<(ms: number) => Promise<void>>(() => Promise.resolve());
      const error = await request('/orders', {
        method: 'POST',
        body: {},
        retry503: 3,
        sleep,
      }).catch((e: unknown) => e);
      expect(calls).toBe(4);
      expect(sleep.mock.calls.map((c) => c[0])).toEqual([2000, 2000, 2000]);
      expect(error).toMatchObject({ status: 503, retryAfterS: 2 });
    });

    it('stops retrying as soon as the server recovers', async () => {
      let calls = 0;
      server.use(
        http.post('*/api/v1/orders', () => {
          calls += 1;
          return calls < 3 ? unavailable() : HttpResponse.json({ ok: 1 }, { status: 202 });
        }),
      );
      const result = await request('/orders', {
        method: 'POST',
        body: {},
        retry503: 3,
        sleep: () => Promise.resolve(),
      });
      expect(result).toEqual({ ok: 1 });
      expect(calls).toBe(3);
    });

    it('does not retry by default, nor any other status', async () => {
      let calls = 0;
      server.use(
        http.get('*/api/v1/x', () => {
          calls += 1;
          return unavailable();
        }),
        http.get('*/api/v1/y', () => {
          calls += 10;
          return HttpResponse.json(apiError('X', 'no'), { status: 500 });
        }),
      );
      await request('/x').catch(() => undefined);
      await request('/y', { retry503: 3, sleep: () => Promise.resolve() }).catch(() => undefined);
      expect(calls).toBe(11);
    });

    it('caps a long Retry-After', async () => {
      server.use(
        http.post('*/api/v1/orders', () =>
          HttpResponse.json(apiError('S', 'm'), { status: 503, headers: { 'Retry-After': '120' } }),
        ),
      );
      const sleep = vi.fn<(ms: number) => Promise<void>>(() => Promise.resolve());
      await request('/orders', { method: 'POST', body: {}, retry503: 1, sleep }).catch(
        () => undefined,
      );
      expect(sleep).toHaveBeenCalledWith(5000);
    });
  });
});
