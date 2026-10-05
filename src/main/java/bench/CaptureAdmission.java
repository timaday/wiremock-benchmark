package bench;

/**
 * Responsibility: enumerate capture request admission outcomes and their HTTP representation.
 * Must not: represent broker failures as client validation errors.
 * Contract: docs/CONTRACT.md, client validation.
 */
enum CaptureAdmission {
  ACCEPTED(200, ""),
  INVALID_CORRELATION(400, "Exactly one nonblank X-Bench-Run and X-Bench-Id is required (maximum 256 characters each)."),
  REQUEST_TOO_LARGE(413, "Benchmark request body exceeds the 64 KiB capture admission limit.");

  final int status;
  final String message;

  CaptureAdmission(int status, String message) {
    this.status = status;
    this.message = message;
  }
}
