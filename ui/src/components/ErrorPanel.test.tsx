import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { ErrorPanel } from './ErrorPanel';

const failure = (message: string) =>
  new ApiError({ status: 200, code: 'BAD_RESPONSE', message, correlationId: 'c-1' });

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ErrorPanel', () => {
  it('takes focus once per distinct failure, never scrolling the page to it', () => {
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    const { rerender } = render(<ErrorPanel error={failure('Unreadable.')} title="Could not" />);
    expect(focus).toHaveBeenCalledTimes(1);
    expect(focus).toHaveBeenLastCalledWith({ preventScroll: true });

    // a background refetch failing the same way is a new object, not a new failure
    rerender(<ErrorPanel error={failure('Unreadable.')} title="Could not" />);
    expect(focus).toHaveBeenCalledTimes(1);

    rerender(<ErrorPanel error={failure('Something else.')} title="Could not" />);
    expect(focus).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('alert')).toHaveTextContent('Something else.');
  });
});
