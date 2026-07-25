import 'package:flutter/material.dart';

import '../screens/login_page.dart';
import '../services/api_client.dart';
import 'auth_state.dart';

/// Shared session-expiry UX for Tickets / KB / Admin / Ask (not Chat-only).
class SessionExpiry {
  SessionExpiry._();

  static const message = 'Your session expired. Please log in again.';

  static bool _handling = false;
  static AuthController? _auth;
  static GlobalKey<NavigatorState>? _navigatorKey;

  /// Wire once from [MyApp]: clears dead JWTs and opens Login on Bearer 401s.
  static void bind({
    required AuthController auth,
    required GlobalKey<NavigatorState> navigatorKey,
  }) {
    _auth = auth;
    _navigatorKey = navigatorKey;
    ApiClient.onUnauthorized = _handleUnauthorized;
  }

  static void unbind() {
    if (ApiClient.onUnauthorized == _handleUnauthorized) {
      ApiClient.onUnauthorized = null;
    }
    _auth = null;
    _navigatorKey = null;
    _handling = false;
  }

  static Future<void> _handleUnauthorized(ApiResult result, String url) async {
    if (_handling) return;
    _handling = true;
    try {
      final auth = _auth;
      if (auth != null && auth.isAuthenticated) {
        await auth.logout();
      } else if (auth != null) {
        // Dead token may still be in memory/storage without a loaded user.
        await auth.logout();
      }

      final nav = _navigatorKey?.currentState;
      final context = _navigatorKey?.currentContext;
      if (nav == null) return;

      if (context != null && context.mounted) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
          const SnackBar(content: Text(message)),
        );
        // Avoid stacking Login if the user is already signing in.
        final routeName = ModalRoute.of(context)?.settings.name;
        if (routeName == LoginPage.routeName) return;
      }

      await nav.push(
        MaterialPageRoute(
          settings: const RouteSettings(name: LoginPage.routeName),
          builder: (_) => const LoginPage(message: message),
        ),
      );
    } finally {
      _handling = false;
    }
  }
}
