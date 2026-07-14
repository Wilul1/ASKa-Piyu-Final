import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/main.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/student_home.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/widgets/sidebar.dart';

void main() {
  testWidgets('student home shows ASKa-Piyu entry points',
      (WidgetTester tester) async {
    await tester.pumpWidget(const MyApp());

    expect(find.text('Welcome back'), findsOneWidget);
    expect(find.text('Public support center'), findsOneWidget);
    expect(find.text('Ask ASKa-Piyu'), findsWidgets);
    expect(find.text('Knowledge Base'), findsWidgets);
    expect(find.text('Admin Dashboard'), findsNothing);
    expect(find.text('Office Dashboard'), findsNothing);
    expect(find.text('Assigned Tickets'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
    expect(find.text('Knowledge Base Admin'), findsNothing);
    expect(find.text('Users & Roles'), findsNothing);
    expect(find.text('Offices'), findsNothing);
    expect(find.text('Reports / Statistics'), findsNothing);
    expect(find.text('My Tickets'), findsNothing);
    expect(find.text('Submit Ticket'), findsNothing);
  });

  testWidgets('guest sidebar hides authenticated navigation',
      (WidgetTester tester) async {
    await tester.pumpWidget(_sidebarHarness(AuthController()));

    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Knowledge Base'), findsOneWidget);
    expect(find.text('Ask ASKa-Piyu'), findsOneWidget);
    expect(find.text('Login'), findsOneWidget);
    expect(find.text('Admin Dashboard'), findsNothing);
    expect(find.text('Office Dashboard'), findsNothing);
    expect(find.text('Assigned Tickets'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
    expect(find.text('Knowledge Base Admin'), findsNothing);
    expect(find.text('Users & Roles'), findsNothing);
    expect(find.text('Offices'), findsNothing);
    expect(find.text('Reports / Statistics'), findsNothing);
    expect(find.text('My Tickets'), findsNothing);
    expect(find.text('Submit Ticket'), findsNothing);
    expect(find.text('Logout'), findsNothing);
  });

  testWidgets('student sidebar shows only student ticket navigation',
      (WidgetTester tester) async {
    final controller = await _authenticatedController('student');

    await tester.pumpWidget(_sidebarHarness(controller));

    expect(find.text('My Tickets'), findsOneWidget);
    expect(find.text('Submit Ticket'), findsOneWidget);
    expect(find.text('Logout'), findsOneWidget);
    expect(find.text('Admin Dashboard'), findsNothing);
    expect(find.text('Office Dashboard'), findsNothing);
    expect(find.text('Assigned Tickets'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
    expect(find.text('Knowledge Base Admin'), findsNothing);
    expect(find.text('Users & Roles'), findsNothing);
    expect(find.text('Offices'), findsNothing);
    expect(find.text('Reports / Statistics'), findsNothing);
  });

  testWidgets('admin sidebar shows admin tools without student tickets',
      (WidgetTester tester) async {
    final controller = await _authenticatedController(' Admin ');

    await tester.pumpWidget(_sidebarHarness(controller));

    expect(find.text('Admin Dashboard'), findsOneWidget);
    expect(find.text('All Tickets'), findsOneWidget);
    expect(find.text('Knowledge Base Admin'), findsOneWidget);
    expect(find.text('Users & Roles'), findsOneWidget);
    expect(find.text('Offices'), findsOneWidget);
    expect(find.text('Reports / Statistics'), findsOneWidget);
    expect(find.text('Logout'), findsOneWidget);
    expect(find.text('My Tickets'), findsNothing);
    expect(find.text('Submit Ticket'), findsNothing);
    expect(find.text('Office Dashboard'), findsNothing);
    expect(find.text('Assigned Tickets'), findsNothing);
  });

  testWidgets('office sidebar shows office tools without student or admin pages',
      (WidgetTester tester) async {
    final controller = await _authenticatedController('office');

    await tester.pumpWidget(_sidebarHarness(controller));

    expect(find.text('Office Dashboard'), findsOneWidget);
    expect(find.text('Assigned Tickets'), findsOneWidget);
    expect(find.text('Logout'), findsOneWidget);
    expect(find.text('My Tickets'), findsNothing);
    expect(find.text('Submit Ticket'), findsNothing);
    expect(find.text('Admin Dashboard'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
    expect(find.text('Knowledge Base Admin'), findsNothing);
    expect(find.text('Users & Roles'), findsNothing);
    expect(find.text('Offices'), findsNothing);
    expect(find.text('Reports / Statistics'), findsNothing);
  });

  testWidgets('home support label follows the authenticated role',
      (WidgetTester tester) async {
    final studentController = await _authenticatedController('student');
    await tester.pumpWidget(_homeHarness(studentController));
    expect(find.text('Student support center'), findsOneWidget);

    final adminController = await _authenticatedController('admin');
    await tester.pumpWidget(_homeHarness(adminController));
    expect(find.text('Admin workspace'), findsOneWidget);
  });
}

Widget _sidebarHarness(AuthController controller) {
  return AuthScope(
    controller: controller,
    child: const MaterialApp(
      home: Scaffold(
        body: SizedBox(width: 260, child: AppSidebar()),
      ),
    ),
  );
}

Widget _homeHarness(AuthController controller) {
  return AuthScope(
    controller: controller,
    child: const MaterialApp(
      home: StudentHomePage(),
    ),
  );
}

Future<AuthController> _authenticatedController(String role) async {
  final controller = AuthController(service: _FakeAuthService(_user(role)));
  await controller.login(const LoginRequest(
    email: 'test@example.edu',
    password: 'password',
  ));
  return controller;
}

AuthUser _user(String role) {
  return AuthUser(
    id: '$role-1',
    email: '$role@example.edu',
    fullName: '$role User',
    role: role,
    officeId: role == 'office' ? 'office-1' : null,
    officeName: role == 'office' ? 'ICT Office' : null,
    studentId: role == 'student' ? '2026-0001' : null,
    createdAt: null,
    updatedAt: null,
  );
}

class _FakeAuthService extends AuthService {
  final AuthUser user;
  String? _token;

  _FakeAuthService(this.user);

  @override
  String? readAccessToken() => _token;

  @override
  void storeAccessToken(String token) {
    _token = token;
  }

  @override
  void clearAccessToken() {
    _token = null;
  }

  @override
  Future<AuthResponse> login(LoginRequest payload) async {
    return AuthResponse(
      accessToken: 'token-${user.role}',
      tokenType: 'bearer',
      user: user,
    );
  }

  @override
  Future<AuthUser> getCurrentUser(String token) async => user;
}
