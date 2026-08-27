import '../app_config.dart';
import '../models/auth_models.dart';
import 'api_client.dart';
import 'local_store.dart';

/// Thrown by auth API calls so UI can tell session death from network blips.
class AuthRequestException implements Exception {
  AuthRequestException(
    this.message, {
    this.statusCode,
    this.isUnauthorized = false,
  });

  final String message;
  final int? statusCode;

  /// True for 401/403 — safe to clear the stored JWT.
  final bool isUnauthorized;

  /// Timeouts, DNS, connection resets, 5xx — keep the session token.
  bool get isTransient => !isUnauthorized;

  @override
  String toString() => message;
}

class AuthService {
  Future<String?> readAccessToken() => LocalStore.readSecureToken();

  Future<void> storeAccessToken(String token, {required bool persist}) async {
    await LocalStore.storeAccessToken(token, persist: persist);
  }

  Future<void> clearAccessToken() async {
    await LocalStore.clearAccessToken();
  }

  /// Revokes the bearer token server-side (bumps credentials_version).
  /// Best-effort: network failures are ignored so local logout still works.
  Future<void> logoutRemote(String accessToken) async {
    final token = accessToken.trim();
    if (token.isEmpty) return;
    try {
      await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/auth/logout',
        headers: {'Authorization': 'Bearer $token'},
      );
    } catch (_) {
      // Offline / blip — local clear still proceeds.
    }
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

  Future<AuthResponse> verifyEmail({
    required String code,
    required String accessToken,
  }) async {
    final result = await ApiClient.send(
      method: 'POST',
      url: '${AppConfig.resolvedApiBase}/auth/verify-email',
      headers: {'Authorization': 'Bearer $accessToken'},
      jsonBody: {'code': code.trim()},
    );
    final data = result.jsonObject;
    if (!result.ok) {
      throw AuthRequestException(
        ApiClient.extractError(data, fallback: 'Could not verify email.'),
        statusCode: result.statusCode,
        isUnauthorized: result.statusCode == 401 || result.statusCode == 403,
      );
    }
    return AuthResponse.fromJson(data);
  }

  Future<({bool sent, String message})> resendVerification({
    required String accessToken,
  }) async {
    final result = await ApiClient.send(
      method: 'POST',
      url: '${AppConfig.resolvedApiBase}/auth/resend-verification',
      headers: {'Authorization': 'Bearer $accessToken'},
    );
    final data = result.jsonObject;
    if (!result.ok) {
      throw AuthRequestException(
        ApiClient.extractError(
          data,
          fallback: 'Could not resend the verification code.',
        ),
        statusCode: result.statusCode,
        isUnauthorized: result.statusCode == 401 || result.statusCode == 403,
      );
    }
    return (
      sent: data['sent'] == true,
      message: (data['message'] ?? 'Check your email for a new code.').toString(),
    );
  }

  Future<AuthResponse> changePassword(
    ChangePasswordRequest payload, {
    required String accessToken,
  }) async {
    final result = await ApiClient.send(
      method: 'POST',
      url: '${AppConfig.resolvedApiBase}/auth/change-password',
      headers: {'Authorization': 'Bearer $accessToken'},
      jsonBody: payload.toJson(),
    );
    final data = result.jsonObject;
    if (!result.ok) {
      throw AuthRequestException(
        ApiClient.extractError(data, fallback: 'Could not change password.'),
        statusCode: result.statusCode,
        isUnauthorized: result.statusCode == 401 || result.statusCode == 403,
      );
    }
    return AuthResponse.fromJson(data);
  }

  Future<AuthUser> getCurrentUser(String token) async {
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/auth/me',
        headers: {'Authorization': 'Bearer $token'},
      );
      final data = result.jsonObject;
      if (!result.ok) {
        throw AuthRequestException(
          ApiClient.extractError(data, fallback: 'Could not load your account.'),
          statusCode: result.statusCode,
          isUnauthorized: result.statusCode == 401 || result.statusCode == 403,
        );
      }
      return AuthUser.fromJson(data);
    } on AuthRequestException {
      rethrow;
    } catch (_) {
      throw AuthRequestException(
        'Could not reach the server to verify your session.',
        statusCode: null,
        isUnauthorized: false,
      );
    }
  }

  Future<Map<String, dynamic>> _sendJson(
    String method,
    String url,
    Map<String, dynamic> body,
  ) async {
    final result = await ApiClient.send(
      method: method,
      url: url,
      jsonBody: body,
    );
    final data = result.jsonObject;
    if (!result.ok) {
      throw StateError(
        ApiClient.extractError(data, fallback: 'Authentication failed.'),
      );
    }
    return data;
  }
}
