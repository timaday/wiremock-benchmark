package bench;

/**
 * Responsibility: resolve and validate required environment settings.
 * Must not: substitute missing settings or configure services.
 * Contract: docs/CONTRACT.md.
 */
final class Settings {
  static String required(String name) {
    String value = System.getenv(name);
    if (value == null || value.isBlank()) throw new IllegalArgumentException("Missing " + name);
    return value;
  }

  static int number(String name) {
    return Integer.parseInt(required(name));
  }

  static int positiveNumber(String name) {
    int value = number(name);
    if (value <= 0) throw new IllegalArgumentException(name + " must be a positive integer");
    return value;
  }
}
