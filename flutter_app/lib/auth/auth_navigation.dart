import 'package:flutter/material.dart';

import '../navigation/soft_page_route.dart';
import '../screens/admin_management_pages.dart';
import '../screens/login_page.dart';
import '../screens/student_home.dart';
import '../screens/verify_email_page.dart';
import '../widgets/sign_out_confirm_dialog.dart';
import 'auth_state.dart';

const String loginRequiredMessage =
    'Please log in or sign up to submit and track support tickets.';
const String emailVerifyRequiredMessage =
    'Verify your email before submitting or viewing tickets.';
const String adminRequiredMessage =
    'Please log in with an admin account to open admin tools.';
const String officeRequiredMessage =
    'Please log in with an office account to open office tools.';

bool _needsEmailVerification(AuthController auth) {
  final role = (auth.role ?? '').trim().toLowerCase();
  if (role != 'student' && role != 'faculty') return false;
  return !(auth.currentUser?.emailVerified ?? false);
}

/// Login required; for tickets also require a verified email.
Future<void> openProtectedPage(
  BuildContext context, {
  required WidgetBuilder builder,
  String message = loginRequiredMessage,
  bool replace = false,
  bool requireVerifiedEmail = false,
}) async {
  final auth = AuthScope.of(context);
  if (auth.isAuthenticated) {
    if (requireVerifiedEmail && _needsEmailVerification(auth)) {
      final verifyRoute = SoftPageRoute<void>(
        builder: (_) => VerifyEmailPage(
          returnTo: builder,
        ),
      );
      if (replace) {
        await Navigator.of(context).pushReplacement(verifyRoute);
      } else {
        await Navigator.of(context).push(verifyRoute);
      }
      return;
    }
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
  bool? emailVerified,
}) {
  final normalized = role.trim().toLowerCase();
  final verified = emailVerified ??
      AuthScope.of(context).currentUser?.emailVerified ??
      false;
  final needsVerify =
      (normalized == 'student' || normalized == 'faculty') && !verified;
  if (needsVerify) {
    Navigator.of(context).pushReplacement(
      SoftPageRoute<void>(
        builder: (_) => VerifyEmailPage(
          returnTo: returnTo,
          gateRole: gateRole,
        ),
      ),
    );
    return;
  }

  final required = gateRole?.trim().toLowerCase();
  final isStaffRole = normalized == 'office' || normalized == 'admin';
  // Staff accounts only follow returnTo when the login gate explicitly matches
  // their role (e.g. office KB tools). Student/faculty gates honor returnTo.
  final honorReturnTo = returnTo != null &&
      (required != null ? required == normalized : !isStaffRole);
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
Future<bool> confirmSignOut(BuildContext context) {
  return showSignOutConfirmDialog(context);
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
