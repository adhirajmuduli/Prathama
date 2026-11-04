/**
 * Typed API errors.
 *
 * The backend answers every failure with the same envelope, so the frontend
 * can always show the machine-readable code, the human-readable message, and
 * the request identifier that correlates the failure with the server log.
 */

export interface ApiErrorDetails {
  readonly [key: string]: unknown;
}

export interface ApiErrorInit {
  readonly code: string;
  readonly message: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly details: ApiErrorDetails | null;
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly details: ApiErrorDetails | null;

  constructor(init: ApiErrorInit) {
    super(init.message);
    this.name = "ApiError";
    this.code = init.code;
    this.status = init.status;
    this.requestId = init.requestId;
    this.details = init.details;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

export function describeError(error: unknown): string {
  if (isApiError(error)) {
    return error.requestId === null
      ? `${error.message} (${error.code})`
      : `${error.message} (${error.code}, request ${error.requestId})`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unknown error occurred.";
}
