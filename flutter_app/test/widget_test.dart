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
    await tester.pump(); // settle initial auth load frame

    expect(find.text('Welcome to ASKa-Piyu'), findsOneWidget);
    expect(find.text('Search'), findsOneWidget);
    // Floating chat CTA uses full or compact label by viewport width.
    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is Text &&
            (widget.data == 'Chat with ASKa-Piyu' || widget.data == 'Chat'),
      ),
      findsOneWidget,
    );
    expect(find.textContaining('Knowledge Base'), findsWidgets);
    expect(find.text('Admin Dashboard'), findsNothing);
    expect(find.text('Office Dashboard'), findsNothing);
    expect(find.text('Assigned Tickets'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
    expect(find.text('Users & Roles'), findsNothing);
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
    expect(find.text('Dashboard'), findsNothing);
    expect(find.text('Assigned Tickets'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
    expect(find.text('Users & Roles'), findsNothing);
    expect(find.text('Offices'), findsNothing);
    expect(find.text('Reports'), findsNothing);
    expect(find.text('My Tickets'), findsNothing);
    expect(find.text('Submit Ticket'), findsNothing);
    expect(find.text('Announcements'), findsNothing);
    expect(find.text('Abuse Detection'), findsNothing);
    expect(find.text('Logout'), findsNothing);
  });

  testWidgets('student sidebar shows only student ticket navigation',
      (WidgetTester tester) async {
    final controller = await _authenticatedController('student');

    await tester.pumpWidget(_sidebarHarness(controller));

    expect(find.text('My Tickets'), findsOneWidget);
    expect(find.text('Submit Ticket'), findsOneWidget);
    expect(find.text('Settings'), findsOneWidget);
    expect(find.text('Logout'), findsOneWidget);
    expect(find.text('Student support'), findsOneWidget);
    expect(find.text('Announcements'), findsNothing);
    expect(find.text('Abuse Detection'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
    expect(find.text('Assigned Tickets'), findsNothing);
    expect(find.text('Users & Roles'), findsNothing);
    expect(find.text('Offices'), findsNothing);
    expect(find.text('Reports'), findsNothing);
  });

  testWidgets('admin sidebar shows admin tools without student tickets',
      (WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(400, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = await _authenticatedController('admin');

    await tester.pumpWidget(_sidebarHarness(controller));

    expect(find.text('Dashboard'), findsOneWidget);
    expect(find.text('All Tickets'), findsOneWidget);
    expect(find.text('Knowledge Base'), findsOneWidget);
    expect(find.text('Knowledge Article'), findsOneWidget);
    expect(find.text('Users & Roles'), findsOneWidget);
    expect(find.text('Offices'), findsOneWidget);
    expect(find.text('Reports'), findsOneWidget);
    expect(find.text('Logout'), findsOneWidget);
    expect(find.text('Announcements'), findsNothing);
    expect(find.text('Abuse Detection'), findsNothing);
    expect(find.text('My Tickets'), findsNothing);
    expect(find.text('Submit Ticket'), findsNothing);
    expect(find.text('Assigned Tickets'), findsNothing);
    expect(find.text('Account'), findsNothing);
  });

  testWidgets('office sidebar shows office tools without student or admin pages',
      (WidgetTester tester) async {
    final controller = await _authenticatedController('office');

    await tester.pumpWidget(_sidebarHarness(controller));

    expect(find.text('Dashboard'), findsOneWidget);
    expect(find.text('Assigned Tickets'), findsOneWidget);
    expect(find.text('Account'), findsOneWidget);
    expect(find.text('Knowledge Base'), findsOneWidget);
    expect(find.text('Knowledge Article'), findsOneWidget);
    expect(find.text('Logout'), findsOneWidget);
    expect(find.text('My Tickets'), findsNothing);
    expect(find.text('Submit Ticket'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
    expect(find.text('Users & Roles'), findsNothing);
    expect(find.text('Offices'), findsNothing);
    expect(find.text('Reports'), findsNothing);
    expect(find.text('Announcements'), findsNothing);
    expect(find.text('Abuse Detection'), findsNothing);
  });

  testWidgets('sidebar brand subtitle follows student and faculty roles',
      (WidgetTester tester) async {
    final studentController = await _authenticatedController('student');
    await tester.pumpWidget(_sidebarHarness(studentController));
    expect(find.text('Student support'), findsOneWidget);

    final facultyController = await _authenticatedController('faculty');
    await tester.pumpWidget(_sidebarHarness(facultyController));
    expect(find.text('Faculty support'), findsOneWidget);
    expect(find.text('Announcements'), findsNothing);
    expect(find.text('Abuse Detection'), findsNothing);

    // Public landing stays the same brand welcome for authenticated students.
    await tester.pumpWidget(_homeHarness(studentController));
    await tester.pump();
    expect(find.text('Welcome to ASKa-Piyu'), findsOneWidget);
  });
}

Widget _sidebarHarness(AuthController controller) {
  return AuthScope(
    controller: controller,
    child: const MaterialApp(
      home: Scaffold(
        // Tall viewport so lazy ListView sidebars build every nav item.
        body: SizedBox(width: 280, height: 1600, child: AppSidebar()),
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
    emailVerified: true,
    createdAt: null,
    updatedAt: null,
  );
}

class _FakeAuthService extends AuthService {
  final AuthUser user;
  String? _token;

  _FakeAuthService(this.user);

  @override
  Future<String?> readAccessToken() async => _token;

  @override
  Future<void> storeAccessToken(String token, {required bool persist}) async {
    _token = token;
  }

  @override
  Future<void> clearAccessToken() async {
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
