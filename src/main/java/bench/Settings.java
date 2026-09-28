package bench;

/** Required environment settings; explicit errors, no provider or persistence fallback. */
final class Settings {
  static String required(String name) {
    String value = System.getenv(name);
    if (value == null || value.isBlank()) throw new IllegalArgumentException("Missing " + name);
    return value;
  }

  static int number(String name) {
    return Integer.parseInt(required(name));
  }
}
