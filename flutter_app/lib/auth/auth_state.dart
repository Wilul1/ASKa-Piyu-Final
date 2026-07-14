import 'package:flutter/widgets.dart';

import '../models/auth_models.dart';
import '../services/auth_service.dart';

class AuthController extends ChangeNotifier {
  AuthController({AuthService? service}) : _service = service ?? AuthService();

  final AuthService _service;
  AuthUser? _currentUser;
  String? _accessToken;
  bool _isLoading = false;

  AuthUser? get currentUser => _currentUser;
  String? get accessToken => _accessToken;
  bool get isLoading => _isLoading;
  bool get isAuthenticated => _accessToken != null && _currentUser != null;
  String? get role => _currentUser?.role.trim().toLowerCase();

  Future<void> loadCurrentUser() async {
    final token = _service.readAccessToken();
    if (token == null) {
      _accessToken = null;
      _currentUser = null;
      notifyListeners();
      return;
    }

    _isLoading = true;
    _accessToken = token;
    notifyListeners();
    try {
      _currentUser = await _service.getCurrentUser(token);
    } catch (_) {
      _accessToken = null;
      _currentUser = null;
      _service.clearAccessToken();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<AuthUser> login(LoginRequest payload) async {
    final response = await _service.login(payload);
    _acceptAuthResponse(response);
    return response.user;
  }

  Future<AuthUser> signup(SignupRequest payload) async {
    final response = await _service.signup(payload);
    _acceptAuthResponse(response);
    return response.user;
  }

  void logout() {
    _service.clearAccessToken();
    _accessToken = null;
    _currentUser = null;
    notifyListeners();
  }

  Map<String, String> ticketHeaders() {
    final user = _currentUser;
    final token = _accessToken;
    if (user == null || token == null) {
      return const {
        'x-user-id': 'student-001',
        'x-user-role': 'student',
        'x-user-name': 'Student',
        'x-user-email': 'student@test.local',
      };
    }

    return {
      'Authorization': 'Bearer $token',
      'x-user-id': user.id,
      'x-user-role': user.role.trim().toLowerCase(),
      'x-user-name': user.fullName,
      'x-user-email': user.email,
      if (user.officeName != null) 'x-user-office': user.officeName!,
    };
  }

  void _acceptAuthResponse(AuthResponse response) {
    _service.storeAccessToken(response.accessToken);
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
