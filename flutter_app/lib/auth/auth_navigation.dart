import 'package:flutter/material.dart';

import '../screens/login_page.dart';
import '../screens/my_tickets_page.dart';
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
    BuildContext context, String role, WidgetBuilder? returnTo) {
  final target = returnTo ?? _defaultTarget(role);
  Navigator.of(context).pushReplacement(MaterialPageRoute(builder: target));
}

WidgetBuilder _defaultTarget(String role) {
  if (role == 'student') {
    return (_) => const MyTicketsPage();
  }
  return (_) => const StudentHomePage();
}
