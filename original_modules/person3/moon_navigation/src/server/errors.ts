import type { ApiErrorBody } from "../shared/types.js";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

export function errorBody(
  code: string,
  message: string,
  requestId: string,
  details?: unknown,
): ApiErrorBody {
  return {
    error: { code, message, ...(details !== undefined ? { details } : {}) },
    request_id: requestId,
    timestamp_utc: new Date().toISOString(),
  };
}

/** Error codes (stable contract):
 * VALIDATION_ERROR 400, INVALID_JSON 400, OUT_OF_COVERAGE 422, NO_ROUTE_FOUND 422,
 * NOT_FOUND 404, UPSTREAM_UNAVAILABLE (never returned as error; falls back to MOCK), INTERNAL_ERROR 500
 */
