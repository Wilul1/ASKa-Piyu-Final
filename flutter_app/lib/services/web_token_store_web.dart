// ignore: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:html' as html;

/// Web token storage:
/// - localStorage: Remember me (survives browser restart)
/// - sessionStorage: same-tab session only (Remember me off)

Future<String?> readWebLocalToken(String key) async {
  final value = html.window.localStorage[key]?.trim();
  return value == null || value.isEmpty ? null : value;
}

Future<void> writeWebLocalToken(String key, String value) async {
  html.window.localStorage[key] = value;
}

Future<void> clearWebLocalToken(String key) async {
  html.window.localStorage.remove(key);
}

Future<String?> readWebSessionToken(String key) async {
  final value = html.window.sessionStorage[key]?.trim();
  return value == null || value.isEmpty ? null : value;
}

Future<void> writeWebSessionToken(String key, String value) async {
  html.window.sessionStorage[key] = value;
}

Future<void> clearWebSessionToken(String key) async {
  html.window.sessionStorage.remove(key);
}
