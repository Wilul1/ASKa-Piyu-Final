import 'package:flutter/widgets.dart';

import '../models/auth_models.dart';
import '../services/auth_service.dart';
import '../services/local_store.dart';

class AuthController extends ChangeNotifier {
  AuthController({AuthService? service}) : _service = service ?? AuthService();

  final AuthService _service;
  AuthUser? _currentUser;
  String? _accessToken;
  bool _isLoading = false;
  bool _rememberMe = true;

  AuthUser? get currentUser => _currentUser;
  String? get accessToken => _accessToken;
  bool get isLoading => _isLoading;
  /// Session token present. Profile may be briefly null after a network blip.
  bool get isAuthenticated => (_accessToken ?? '').trim().isNotEmpty;
  String? get role => _currentUser?.role.trim().toLowerCase();

  Future<void> loadCurrentUser() async {
    final token = await _service.readAccessToken();
    if (token == null) {
      _accessToken = null;
      _currentUser = null;
      _rememberMe = true;
      notifyListeners();
      return;
    }

    _isLoading = true;
    _accessToken = token;
    // Keep Remember-me preference aligned with where the token was stored.
    _rememberMe = await LocalStore.hasDurableAccessToken();
    notifyListeners();
    try {
      _currentUser = await _loadProfileWithRetries(token);
    } on AuthRequestException catch (error) {
      if (error.isUnauthorized) {
        _accessToken = null;
        _currentUser = null;
        await _service.clearAccessToken();
      }
      // Transient blip: keep JWT so the user is not force-logged-out.
    } catch (_) {
      // Keep JWT on unexpected failures during profile load.
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<AuthUser> _loadProfileWithRetries(String token) async {
    AuthRequestException? lastTransient;
    for (var attempt = 0; attempt < 3; attempt++) {
      if (attempt > 0) {
        await Future<void>.delayed(Duration(milliseconds: 350 * attempt));
      }
      try {
        return await _service.getCurrentUser(token);
      } on AuthRequestException catch (error) {
        if (error.isUnauthorized) rethrow;
        lastTransient = error;
      }
    }
    throw lastTransient ??
        AuthRequestException(
          'Could not reach the server to verify your session.',
        );
  }

  Future<AuthUser> login(
    LoginRequest payload, {
    bool rememberMe = true,
  }) async {
    _rememberMe = rememberMe;
    final response = await _service.login(payload);
    await _acceptAuthResponse(response, persist: rememberMe);
    return response.user;
  }

  Future<AuthUser> signup(SignupRequest payload) async {
    final response = await _service.signup(payload);
    await _acceptAuthResponse(response, persist: true);
    return response.user;
  }

  /// Changes password and replaces the session token (old JWT is revoked).
  Future<AuthUser> changePassword(ChangePasswordRequest payload) async {
    final token = _accessToken;
    if (token == null || token.trim().isEmpty) {
      throw StateError('You must be signed in to change your password.');
    }
    final response = await _service.changePassword(
      payload,
      accessToken: token,
    );
    await _acceptAuthResponse(response, persist: _rememberMe);
    return response.user;
  }

  Future<void> logout() async {
    await _service.clearAccessToken();
    _accessToken = null;
    _currentUser = null;
    notifyListeners();
  }

  Map<String, String> ticketHeaders() {
    final token = _accessToken;
    if (token == null) {
      return const {};
    }

    return {
      'Authorization': 'Bearer $token',
    };
  }

  Future<void> _acceptAuthResponse(
    AuthResponse response, {
    required bool persist,
  }) async {
    await _service.storeAccessToken(response.accessToken, persist: persist);
    _accessToken = response.accessToken;
    _currentUser = response.user;
    notifyListeners();
  }
}

class AuthScope extends InheritedNotifier<AuthController> {
  const AuthScope({
    super.key,
    required AuthController controller,
    required super.child,
  }) : super(notifier: controller);

  static AuthController of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AuthScope>();
    assert(scope != null, 'AuthScope was not found in the widget tree.');
    return scope!.notifier!;
  }
}
