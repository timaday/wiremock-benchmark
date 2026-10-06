package bench;

/**
 * Responsibility: enumerate supported explicit missing-correlation behavior.
 * Must not: select alternate fields or invent business IDs. Contract: docs/CONTRACT.md.
 */
enum MissingCorrelationPolicy { RECORD_UNCORRELATED }
