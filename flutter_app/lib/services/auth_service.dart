import 'dart:convert';
import 'dart:html' as html;

import '../app_config.dart';
import '../models/auth_models.dart';

class AuthService {
  static const String _tokenKey = 'aska_access_token';

  String? readAccessToken() {
    final value = html.window.localStorage[_tokenKey]?.trim();
    return value == null || value.isEmpty ? null : value;
  }

  void storeAccessToken(String token) {
    final cleaned = token.trim();
    if (cleaned.isEmpty) return;
    html.window.localStorage[_tokenKey] = cleaned;
  }

  void clearAccessToken() {
    html.window.localStorage.remove(_tokenKey);
  }

  Future<AuthResponse> signup(SignupRequest payload) async {
    final data = await _sendJson(
      'POST',
      '${AppConfig.resolvedApiBase}/auth/signup',
      payload.toJson(),
    );
    return AuthResponse.fromJson(data);
  }

  Future<AuthResponse> login(LoginRequest payload) async {
    final data = await _sendJson(
      'POST',
      '${AppConfig.resolvedApiBase}/auth/login',
      payload.toJson(),
    );
    return AuthResponse.fromJson(data);
  }

  Future<AuthUser> getCurrentUser(String token) async {
    final request = html.HttpRequest();
    request.open('GET', '${AppConfig.resolvedApiBase}/auth/me');
    request.setRequestHeader('Authorization', 'Bearer $token');
    request.send();
    await request.onLoadEnd.first;
    final data = _decodeObject(request.responseText);
    final statusCode = request.status ?? 0;
    if (statusCode < 200 || statusCode >= 300) {
      throw StateError(_extractError(data, 'Could not load your account.'));
    }
    return AuthUser.fromJson(data);
  }

  Future<Map<String, dynamic>> _sendJson(
    String method,
    String url,
    Map<String, dynamic> body,
  ) async {
    final request = html.HttpRequest();
    request.open(method, url);
    request.setRequestHeader('Content-Type', 'application/json');
    request.send(jsonEncode(body));
    await request.onLoadEnd.first;
    final data = _decodeObject(request.responseText);
    final statusCode = request.status ?? 0;
    if (statusCode < 200 || statusCode >= 300) {
      throw StateError(_extractError(data, 'Authentication failed.'));
    }
    return data;
  }
}

Map<String, dynamic> _decodeObject(String? responseText) {
  final text = (responseText ?? '').trim();
  if (text.isEmpty) return <String, dynamic>{};
  try {
    final decoded = jsonDecode(text);
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
  } catch (_) {
    return <String, dynamic>{'detail': text};
  }
}

String _extractError(Map<String, dynamic> data, String fallback) {
  final detail = data['detail'];
  if (detail is String && detail.trim().isNotEmpty) return detail;
  if (detail is List && detail.isNotEmpty) {
    return detail.map((item) => item.toString()).join('\n');
  }
  final message = data['message'];
  if (message is String && message.trim().isNotEmpty) return message;
  return fallback;
}
