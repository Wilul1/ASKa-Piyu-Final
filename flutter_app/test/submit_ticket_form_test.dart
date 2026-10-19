import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/my_tickets_page.dart';
import 'package:aska_piyu/services/auth_service.dart';

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

  Future<AuthController> buildLoggedInController() async {
    final controller = AuthController(service: _FakeAuthService(studentUser()));
    await controller.login(
      const LoginRequest(email: 'student@example.edu', password: 'password'),
    );
    return controller;
  }

  Future<void> pumpSubmitTab(
    WidgetTester tester, {
    Size size = const Size(390, 844),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final controller = await buildLoggedInController();
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: const MaterialApp(home: MyTicketsPage(initialTab: 1)),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  Future<void> pumpListTab(
    WidgetTester tester, {
    Size size = const Size(390, 844),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final controller = await buildLoggedInController();
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: const MaterialApp(home: MyTicketsPage()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  // --- Compact banner (Submit Ticket view only) -----------------------

  testWidgets(
      'Submit Ticket shows the small compact banner, not the List view\'s '
      'decorative hero', (tester) async {
    await pumpSubmitTab(tester);

    expect(find.text('Submit a Support Request'), findsOneWidget);
    expect(find.text('Tell us what you need help with.'), findsOneWidget);
    // The full hero's own decorative elements never render here.
    expect(find.text('SUBMIT TICKET'), findsNothing);
    expect(
      find.text(
        'Share your concern and any details the office will need to help you.',
      ),
      findsNothing,
    );
  });

  testWidgets(
      'the List view still shows its full decorative hero, unaffected by '
      'the Submit Ticket banner change', (tester) async {
    await pumpListTab(tester);

    expect(find.text('TICKETS'), findsOneWidget);
    expect(find.text('My Tickets'), findsOneWidget);
    expect(
      find.textContaining('Create support requests, track progress'),
      findsOneWidget,
    );
    // The compact Submit Ticket banner's own copy never renders here.
    expect(find.text('Tell us what you need help with.'), findsNothing);
  });

  // --- Compact form copy -------------------------------------------------

  testWidgets(
      'on a phone, the office field\'s long standalone explainer paragraph '
      'is gone and the helper text is shortened', (tester) async {
    await pumpSubmitTab(tester, size: const Size(390, 844));

    expect(
      find.text('Choose an office, or leave on Automatic routing.'),
      findsOneWidget,
    );
    expect(
      find.textContaining('Not sure which office handles your concern?'),
      findsNothing,
    );
  });

  testWidgets('on a wide (desktop) layout, the original full helper copy is preserved',
      (tester) async {
    await pumpSubmitTab(tester, size: const Size(1200, 900));

    expect(
      find.text('Select the office you want to send this ticket to.'),
      findsOneWidget,
    );
    expect(
      find.textContaining('Not sure which office handles your concern?'),
      findsOneWidget,
    );
  });

  // --- Preserved functionality --------------------------------------------

  testWidgets(
      'all fields, the attachment picker, and both actions are still '
      'present on the compact phone layout', (tester) async {
    await pumpSubmitTab(tester);

    expect(find.text('Office (optional)'), findsOneWidget);
    expect(find.text('Subject'), findsOneWidget);
    expect(find.text('Description'), findsOneWidget);
    expect(find.text('Attachment (optional)'), findsOneWidget);
    expect(find.text('Automatic routing — Let ASKa-Piyu choose'), findsWidgets);
    expect(find.text('Submit Ticket'), findsOneWidget);
    expect(find.text('Clear'), findsOneWidget);
  });

  testWidgets('submitting with an empty subject still shows the existing '
      'validation error (validation behavior unchanged)', (tester) async {
    await pumpSubmitTab(tester);

    // The form scrolls internally on a phone -- the button starts below
    // the fold, same as before this change.
    await tester.ensureVisible(find.text('Submit Ticket'));
    await tester.tap(find.text('Submit Ticket'));
    await tester.pump();

    expect(find.text('Subject must be at least 8 characters.'), findsOneWidget);
  });

  // --- Responsive: no overflow at the required widths -----------------

  for (final width in <double>[360, 390, 430, 768, 1024, 1400]) {
    testWidgets(
        'the Submit Ticket view has no overflow at width ${width.toInt()}px',
        (tester) async {
      final unexpectedErrors = <String>[];
      final previousOnError = FlutterError.onError;
      FlutterError.onError = (details) {
        unexpectedErrors.add(details.toString());
        previousOnError?.call(details);
      };
      addTearDown(() => FlutterError.onError = previousOnError);

      await pumpSubmitTab(tester, size: Size(width, 900));

      expect(unexpectedErrors, isEmpty);
      expect(find.text('Submit a Support Request'), findsOneWidget);
      expect(find.text('Office (optional)'), findsOneWidget);
      expect(find.text('Subject'), findsOneWidget);
      expect(find.text('Description'), findsOneWidget);
      expect(find.text('Submit Ticket'), findsOneWidget);
    });
  }

  // --- Measurement: how much higher the form now starts -------------------
  //
  // Not a pass/fail assertion -- prints the measured Y position of the
  // first form field (the Office label) on a representative phone width,
  // for the "what vertical space was removed" report. The banner's own
  // old height was computed by hand from the original _TicketsHeroBanner
  // code (padding 18+20+34, eyebrow+title(24pt)+8+subtitle(13pt, up to 2
  // lines) -- see the task report).

  testWidgets('measurement: Office label Y position on a 390px phone',
      (tester) async {
    await pumpSubmitTab(tester, size: const Size(390, 844));

    final y = tester.getTopLeft(find.text('Office (optional)')).dy;
    // ignore: avoid_print
    print('MEASURED Office label Y (390px, compact banner) = $y');
    expect(y, greaterThan(0));
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
