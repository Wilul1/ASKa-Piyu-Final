import 'dart:html' as html;

class AppConfig {
  static const String apiBase =
      String.fromEnvironment('ASKA_API_BASE_URL', defaultValue: '');

  static String get resolvedApiBase {
    final configured = apiBase.trim();
    if (configured.endsWith('/')) {
      return configured.substring(0, configured.length - 1);
    }
    return configured;
  }

  static Map<String, String> studentHeaders() {
    return {
      'x-user-id': 'student-001',
      'x-user-role': 'student',
      'x-user-name': 'Student',
      'x-user-email': 'student@test.local',
    };
  }

  static String? get savedAdminKey {
    final value = html.window.localStorage['aska_admin_key']?.trim();
    return value == null || value.isEmpty ? null : value;
  }

  static set savedAdminKey(String? value) {
    final cleaned = value?.trim() ?? '';
    if (cleaned.isEmpty) {
      html.window.localStorage.remove('aska_admin_key');
      return;
    }
    html.window.localStorage['aska_admin_key'] = cleaned;
  }
}
