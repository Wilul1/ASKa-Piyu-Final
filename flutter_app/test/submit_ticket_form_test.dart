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

  // --- Compact headings (both tabs; neither has the old decorative hero) --

  testWidgets(
      'Submit Ticket shows its own small compact banner, not the List '
      'view\'s heading', (tester) async {
    await pumpSubmitTab(tester);

    expect(find.text('Submit a Support Request'), findsOneWidget);
    expect(find.text('Tell us what you need help with.'), findsOneWidget);
    expect(find.text('My Tickets'), findsNothing);
  });

  testWidgets(
      'the List view shows only a small compact heading -- no decorative '
      'hero, eyebrow label, or introductory paragraph', (tester) async {
    await pumpListTab(tester);

    expect(find.text('My Tickets'), findsOneWidget);
    // The old hero's own decorative elements (eyebrow label, large wave
    // banner, and introductory subtitle paragraph) are gone entirely.
    expect(find.text('TICKETS'), findsNothing);
    expect(find.text('SUBMIT TICKET'), findsNothing);
    expect(
      find.textContaining('Create support requests, track progress'),
      findsNothing,
    );
    // The compact Submit Ticket banner's own copy never renders here.
    expect(find.text('Tell us what you need help with.'), findsNothing);
  });

  // --- Simple, consistent labels: no numbered badges, no per-field --------
  // explainer paragraphs (HESK-style plain label + input), at every width.

  testWidgets(
      'no field has a standalone explainer paragraph under its label, on '
      'a phone', (tester) async {
    await pumpSubmitTab(tester, size: const Size(390, 844));

    expect(
      find.textContaining('Not sure which office handles your concern?'),
      findsNothing,
    );
    expect(
      find.text('Select the office you want to send this ticket to.'),
      findsNothing,
    );
    expect(find.text('A short summary of what you need help with.'), findsNothing);
    expect(
      find.textContaining('Include dates, reference numbers, offices visited'),
      findsNothing,
    );
  });

  testWidgets(
      'no field has a standalone explainer paragraph under its label, on '
      'a wide (desktop) layout either -- the simplified labels are the '
      'same at every width, not a mobile-only trim', (tester) async {
    await pumpSubmitTab(tester, size: const Size(1200, 900));

    expect(
      find.textContaining('Not sure which office handles your concern?'),
      findsNothing,
    );
    expect(
      find.text('Select the office you want to send this ticket to.'),
      findsNothing,
    );
    expect(find.text('A short summary of what you need help with.'), findsNothing);
  });

  testWidgets(
      "the Subject field has no example-sentence placeholder, and the "
      'Description field uses the short "Describe your concern" placeholder',
      (tester) async {
    await pumpSubmitTab(tester);

    expect(
      find.text('Example: How can I request my transcript of records?'),
      findsNothing,
    );
    expect(
      find.text('Tell us what happened and what help you need.'),
      findsNothing,
    );
    expect(find.text('Describe your concern'), findsOneWidget);
  });

  testWidgets(
      'the Attachment field still shows the essential file-type/size info, '
      'in one compact line, at every width', (tester) async {
    await pumpSubmitTab(tester, size: const Size(390, 844));
    expect(
      find.textContaining('— max 10 MB.'),
      findsOneWidget,
    );

    await pumpSubmitTab(tester, size: const Size(1200, 900));
    expect(
      find.textContaining('— max 10 MB.'),
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

  // --- Notifications: Student Mailbox is now the only place for them ------
  //
  // My Tickets used to show its own unread-notification banner/card
  // (separate state, its own poll, a "Mark all read" action, and up to 3
  // notification previews) above the ticket list. That banner, and all of
  // its supporting state/polling/listener code, has been removed -- the
  // Student Mailbox page is now the single place student notifications
  // are shown. These tests prove the banner is gone from both tabs, while
  // student_mailbox_page_test.dart's own, separate suite continues to
  // prove the Mailbox's own badge/list/mark-read behavior still works
  // unchanged.

  testWidgets(
      'the List view never renders a notification banner, action, or '
      'preview, even after enough time for a background load to settle',
      (tester) async {
    await pumpListTab(tester);
    // Give the (failing, no-backend-in-this-sandbox) initial ticket load
    // and any timer-driven poll a moment to run, same as production would
    // after first paint -- the banner must still never appear.
    await tester.pump(const Duration(seconds: 1));

    // "Mark all read" is the notification banner's own distinguishing
    // action -- it must never appear on My Tickets now, even though the
    // Student Mailbox page still shows a button with this exact text.
    expect(find.widgetWithText(TextButton, 'Mark all read'), findsNothing);
    expect(find.textContaining('unread'), findsNothing);
  });

  testWidgets(
      'the Submit Ticket view never renders a notification banner, '
      'action, or preview either', (tester) async {
    await pumpSubmitTab(tester);
    await tester.pump(const Duration(seconds: 1));

    expect(find.widgetWithText(TextButton, 'Mark all read'), findsNothing);
    expect(find.textContaining('unread'), findsNothing);
  });

  testWidgets(
      'My Tickets still shows its own ticket-list chrome -- compact '
      'heading and status summary -- with the banner gone', (tester) async {
    await pumpListTab(tester);

    expect(find.text('My Tickets'), findsOneWidget);
    // _TicketStatsSummary -- unrelated to, and unaffected by, the removed
    // notification banner.
    expect(find.text('Open'), findsOneWidget);
    expect(find.text('In Progress'), findsOneWidget);
    expect(find.text('Closed'), findsOneWidget);
    expect(find.text('Total'), findsOneWidget);
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
  // for the "what vertical space was removed" report.

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
