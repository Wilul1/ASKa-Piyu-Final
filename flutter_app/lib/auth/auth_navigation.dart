import 'package:flutter/material.dart';

import '../navigation/soft_page_route.dart';
import '../screens/admin_management_pages.dart';
import '../screens/login_page.dart';
import '../screens/student_home.dart';
import 'auth_state.dart';

const String loginRequiredMessage =
    'Please log in or sign up to submit and track support tickets.';
const String adminRequiredMessage =
    'Please log in with an admin account to open admin tools.';
const String officeRequiredMessage =
    'Please log in with an office account to open office tools.';

Future<void> openProtectedPage(
  BuildContext context, {
  required WidgetBuilder builder,
  String message = loginRequiredMessage,
  bool replace = false,
}) async {
  final auth = AuthScope.of(context);
  if (auth.isAuthenticated) {
    final route = SoftPageRoute<void>(builder: builder);
    if (replace) {
      await Navigator.of(context).pushReplacement(route);
    } else {
      await Navigator.of(context).push(route);
    }
    return;
  }

  final loginRoute = SoftPageRoute<void>(
    builder: (_) => LoginPage(returnTo: builder, message: message),
  );
  if (replace) {
    await Navigator.of(context).pushReplacement(loginRoute);
  } else {
    await Navigator.of(context).push(loginRoute);
  }
}

Future<void> openAdminPage(
  BuildContext context, {
  required WidgetBuilder builder,
}) async {
  final auth = AuthScope.of(context);
  if (auth.role == 'admin') {
    await Navigator.of(context).push(SoftPageRoute<void>(builder: builder));
    return;
  }

  if (!auth.isAuthenticated) {
    await Navigator.of(context).push(
      SoftPageRoute<void>(
        builder: (_) => LoginPage(
          returnTo: builder,
          message: adminRequiredMessage,
          gateRole: 'admin',
        ),
      ),
    );
    return;
  }

  ScaffoldMessenger.of(context).showSnackBar(
    const SnackBar(content: Text('Admin access is required for this page.')),
  );
}

Future<void> openOfficePage(
  BuildContext context, {
  required WidgetBuilder builder,
}) async {
  final auth = AuthScope.of(context);
  if (auth.role == 'office') {
    await Navigator.of(context).push(SoftPageRoute<void>(builder: builder));
    return;
  }

  if (!auth.isAuthenticated) {
    await Navigator.of(context).push(
      SoftPageRoute<void>(
        builder: (_) => LoginPage(
          returnTo: builder,
          message: officeRequiredMessage,
          gateRole: 'office',
        ),
      ),
    );
    return;
  }

  ScaffoldMessenger.of(context).showSnackBar(
    const SnackBar(content: Text('Office access is required for this page.')),
  );
}

void redirectAfterAuth(
  BuildContext context,
  String role,
  WidgetBuilder? returnTo, {
  String? gateRole,
}) {
  final normalized = role.trim().toLowerCase();
  final required = gateRole?.trim().toLowerCase();
  final honorReturnTo =
      returnTo != null && (required == null || required == normalized);
  final target = (honorReturnTo ? returnTo : null) ?? _defaultTarget(role);
  Navigator.of(context).pushReplacement(
    SoftPageRoute<void>(builder: target),
  );
}

WidgetBuilder _defaultTarget(String role) {
  final normalized = role.trim().toLowerCase();
  if (normalized == 'office') {
    return (_) => const OfficeDashboardPage();
  }
  if (normalized == 'admin') {
    return (_) => const AdminDashboardPage();
  }
  // Students, faculty, and guests land on the public home (not Ask Assistant).
  return (_) => const StudentHomePage();
}

/// Confirm before signing out (accidental taps in menus/sidebars).
Future<bool> confirmSignOut(BuildContext context) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('Sign out?'),
      content: const Text('Are you sure you want to sign out of ASKa-Piyu?'),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(dialogContext).pop(true),
          child: const Text('Sign out'),
        ),
      ],
    ),
  );
  return confirmed == true;
}

/// Clears the session and returns to the public home page.
///
/// When [confirm] is true (default), asks the user to confirm first.
Future<void> signOutToHome(
  BuildContext context, {
  bool confirm = true,
}) async {
  if (confirm) {
    final ok = await confirmSignOut(context);
    if (!ok || !context.mounted) return;
  }
  await AuthScope.of(context).logout();
  if (!context.mounted) return;
  await softPushAndClear(context, const StudentHomePage());
}
