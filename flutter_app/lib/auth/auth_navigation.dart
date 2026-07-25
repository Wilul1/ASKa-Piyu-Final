import 'package:flutter/material.dart';

import '../screens/admin_management_pages.dart';
import '../screens/chatbot_page.dart';
import '../screens/login_page.dart';
import '../screens/student_home.dart';
import 'auth_state.dart';

const String loginRequiredMessage =
    'Please log in or create an account to submit and track support tickets.';
const String adminRequiredMessage =
    'Please log in with an admin account to open admin tools.';
const String officeRequiredMessage =
    'Please log in with an office account to open office tools.';

Future<void> openProtectedPage(
  BuildContext context, {
  required WidgetBuilder builder,
  String message = loginRequiredMessage,
}) async {
  final auth = AuthScope.of(context);
  if (auth.isAuthenticated) {
    await Navigator.of(context).push(MaterialPageRoute(builder: builder));
    return;
  }

  await Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => LoginPage(returnTo: builder, message: message),
    ),
  );
}

Future<void> openAdminPage(
  BuildContext context, {
  required WidgetBuilder builder,
}) async {
  final auth = AuthScope.of(context);
  if (auth.role == 'admin') {
    await Navigator.of(context).push(MaterialPageRoute(builder: builder));
    return;
  }

  if (!auth.isAuthenticated) {
    await Navigator.of(context).push(
      MaterialPageRoute(
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
    await Navigator.of(context).push(MaterialPageRoute(builder: builder));
    return;
  }

  if (!auth.isAuthenticated) {
    await Navigator.of(context).push(
      MaterialPageRoute(
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
  Navigator.of(context).pushReplacement(MaterialPageRoute(builder: target));
}

WidgetBuilder _defaultTarget(String role) {
  final normalized = role.trim().toLowerCase();
  if (normalized == 'office') {
    return (_) => const OfficeDashboardPage();
  }
  if (normalized == 'admin') {
    return (_) => const AdminDashboardPage();
  }
  // Students and faculty land on Ask Assistant (not My Tickets).
  if (normalized == 'student' || normalized == 'faculty') {
    return (_) => const ChatbotPage();
  }
  return (_) => const StudentHomePage();
}
