import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/student_mailbox_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/widgets/public_site_header.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  AuthUser studentUser() {
    return const AuthUser(
      id: 'student-1',
      email: 'student@example.edu',
      fullName: 'Juan Dela Cruz',
      role: 'student',
      officeId: null,
      officeName: null,
      emailVerified: true,
      createdAt: null,
      updatedAt: null,
    );
  }

  AuthUser officeUser() {
    return const AuthUser(
      id: 'office-1',
      email: 'office@example.edu',
      fullName: 'Registrar Staff',
      role: 'office',
      officeId: 'office-registrar',
      officeName: 'Registrar',
      emailVerified: true,
      createdAt: null,
      updatedAt: null,
    );
  }

  Future<void> pumpHeader(
    WidgetTester tester, {
    AuthUser? user,
    Size size = const Size(1200, 900),
  }) async {
    // PublicSiteHeader reads MediaQuery.sizeOf directly (not via a
    // LayoutBuilder), and tester.binding.setSurfaceSize alone does not
    // reliably propagate to MediaQuery for a widget that reads it this
    // way in this environment -- confirmed by direct measurement.
    // Setting tester.view's physicalSize/devicePixelRatio directly does.
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    AuthController? controller;
    if (user != null) {
      controller = AuthController(service: _FakeAuthService(user));
      await controller.login(
        const LoginRequest(email: 'user@example.edu', password: 'password'),
      );
    } else {
      controller = AuthController(service: _FakeAuthService(studentUser()));
    }

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: const MaterialApp(home: Scaffold(body: PublicSiteHeader())),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  // --- Desktop top navigation -----------------------------------------

  testWidgets('an authenticated student sees a Mailbox link in the desktop nav',
      (tester) async {
    await pumpHeader(tester, user: studentUser());

    expect(find.text('Mailbox'), findsOneWidget);
  });

  testWidgets('a logged-out visitor never sees the Mailbox link',
      (tester) async {
    // pumpHeader's user:null branch builds a controller without ever
    // calling login(), i.e. genuinely unauthenticated.
    await pumpHeader(tester, user: null);

    expect(find.text('Mailbox'), findsNothing);
    expect(find.text('Login'), findsOneWidget);
  });

  testWidgets(
      'office/admin users never see the student Mailbox link, even if they '
      'reach this shared header', (tester) async {
    await pumpHeader(tester, user: officeUser());

    expect(find.text('Mailbox'), findsNothing);
  });

  testWidgets('tapping Mailbox opens StudentMailboxPage', (tester) async {
    await pumpHeader(tester, user: studentUser());

    await tester.tap(find.text('Mailbox'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 80));

    expect(find.byType(StudentMailboxPage), findsOneWidget);
  });

  testWidgets(
      'no "Sign out" button in the desktop nav -- it lives on Account now',
      (tester) async {
    await pumpHeader(tester, user: studentUser());

    expect(find.text('Sign out'), findsNothing);
    // The authenticated identity link (labeled "Account" for a student) is
    // still there -- only the separate, redundant sign-out control is gone.
    expect(find.text('Account'), findsOneWidget);
  });

  // --- Mobile slide-out menu -------------------------------------------

  Future<void> openMobileMenu(WidgetTester tester) async {
    await tester.tap(find.byTooltip('Menu'));
    await tester.pumpAndSettle();
  }

  testWidgets(
      'the mobile slide-out menu lists Mailbox alongside the other student '
      'items for an authenticated student', (tester) async {
    await pumpHeader(tester, user: studentUser(), size: const Size(390, 844));
    await openMobileMenu(tester);

    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Knowledge Base'), findsOneWidget);
    expect(find.text('Ask Assistant'), findsOneWidget);
    expect(find.text('My Tickets'), findsOneWidget);
    expect(find.text('Mailbox'), findsOneWidget);
    // "Account" legitimately matches twice here: the section header label
    // and the nav item itself.
    expect(find.text('Account'), findsWidgets);
  });

  testWidgets('office/admin never see Mailbox in the mobile menu either',
      (tester) async {
    await pumpHeader(tester, user: officeUser(), size: const Size(390, 844));
    await openMobileMenu(tester);

    expect(find.text('Mailbox'), findsNothing);
  });

  testWidgets('no "Sign out" item in the mobile slide-out menu',
      (tester) async {
    await pumpHeader(tester, user: studentUser(), size: const Size(390, 844));
    await openMobileMenu(tester);

    expect(find.text('Sign out'), findsNothing);
  });

  testWidgets('tapping Mailbox in the mobile menu opens StudentMailboxPage',
      (tester) async {
    await pumpHeader(tester, user: studentUser(), size: const Size(390, 844));
    await openMobileMenu(tester);

    await tester.tap(find.text('Mailbox'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 80));

    expect(find.byType(StudentMailboxPage), findsOneWidget);
  });
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
