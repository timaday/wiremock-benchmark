package bench;

/**
 * Responsibility: describe the outcome of extracting business correlation.
 * Must not: conflate missing correlation with lost capture. Contract: docs/CONTRACT.md.
 */
public enum CorrelationStatus { PRESENT, MISSING, INVALID_BODY, INVALID_VALUE }
