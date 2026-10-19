import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/student_mailbox_page.dart';
import 'package:aska_piyu/services/auth_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Map<String, dynamic> notificationJson({
    required String id,
    String? ticketId = 'TK-20261013-07BA4C',
    String type = 'ticket_reply',
    String title = 'New reply on TK-20261013-07BA4C',
    String body = 'The Registrar replied to your ticket.',
    bool isRead = false,
    String createdAt = '2026-10-13T12:00:00Z',
  }) {
    return {
      'id': id,
      'ticket_id': ticketId,
      'type': type,
      'title': title,
      'body': body,
      'is_read': isRead,
      'created_at': createdAt,
    };
  }

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

  Future<void> pumpMailbox(
    WidgetTester tester, {
    List<Map<String, dynamic>>? notifications,
    Size size = const Size(1200, 900),
  }) async {
    // StudentMailboxPage embeds PublicSiteHeader, which reads
    // MediaQuery.sizeOf directly rather than via a LayoutBuilder; setting
    // tester.view directly (not tester.binding.setSurfaceSize) is what
    // reliably propagates to it in this environment.
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final controller = AuthController(service: _FakeAuthService(studentUser()));
    await controller.login(
      const LoginRequest(email: 'student@example.edu', password: 'password'),
    );

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: StudentMailboxPage(debugNotifications: notifications ?? const []),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('populated mailbox shows title, unread badge, and each notification',
      (tester) async {
    await pumpMailbox(
      tester,
      notifications: [
        notificationJson(id: 'n-1', isRead: false),
        notificationJson(
          id: 'n-2',
          type: 'status_changed',
          title: 'Ticket TK-20261013-07BA4C is now Resolved',
          body: 'Status updated from In Progress to Resolved by Registrar Staff.',
          isRead: true,
        ),
      ],
    );

    // At this default wide width the header's own "Mailbox" nav link
    // (now active) legitimately matches too, alongside this page's title.
    expect(find.text('Mailbox'), findsWidgets);
    // One unread of the two seeded.
    expect(find.text('1'), findsOneWidget);
    expect(find.text('New reply on TK-20261013-07BA4C'), findsOneWidget);
    expect(find.text('The Registrar replied to your ticket.'), findsOneWidget);
    expect(find.text('Ticket TK-20261013-07BA4C is now Resolved'), findsOneWidget);
    expect(find.textContaining('Ticket #TK-20261013-07BA4C'), findsWidgets);
  });

  testWidgets('empty mailbox shows a clear, non-fake empty state', (tester) async {
    await pumpMailbox(tester, notifications: const []);

    expect(find.text('Mailbox is empty'), findsOneWidget);
    expect(
      find.textContaining('new replies, status changes, and reassignments'),
      findsOneWidget,
    );
  });

  testWidgets(
      'Mark all read is disabled with no unread count badge when everything '
      'is already read', (tester) async {
    await pumpMailbox(
      tester,
      notifications: [notificationJson(id: 'n-1', isRead: true)],
    );

    final button = tester.widget<TextButton>(
      find.widgetWithText(TextButton, 'Mark all read'),
    );
    expect(button.onPressed, isNull);
    // No unread-count pill rendered when the count is zero.
    expect(find.text('0'), findsNothing);
  });

  testWidgets('Mark all read is enabled when there is an unread notification',
      (tester) async {
    await pumpMailbox(
      tester,
      notifications: [notificationJson(id: 'n-1', isRead: false)],
    );

    final button = tester.widget<TextButton>(
      find.widgetWithText(TextButton, 'Mark all read'),
    );
    expect(button.onPressed, isNotNull);
  });

  testWidgets(
      'tapping Mark all read surfaces an error in this sandbox (no backend '
      'reachable) rather than silently doing nothing', (tester) async {
    await pumpMailbox(
      tester,
      notifications: [notificationJson(id: 'n-1', isRead: false)],
    );

    await tester.tap(find.widgetWithText(TextButton, 'Mark all read'));
    await tester.pumpAndSettle();

    expect(find.byType(SnackBar), findsOneWidget);
  });

  testWidgets(
      'tapping a notification that references a ticket attempts to open it '
      '(fails gracefully in this sandbox, never crashes)', (tester) async {
    await pumpMailbox(
      tester,
      notifications: [notificationJson(id: 'n-1', ticketId: 'TK-OPEN-1')],
    );

    await tester.tap(find.text('New reply on TK-20261013-07BA4C'));
    await tester.pumpAndSettle();

    // No reachable backend in this sandbox: the ticket fetch fails, so no
    // TicketDetailsPage opens, but the failure is surfaced, not swallowed.
    expect(find.byType(SnackBar), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('mailbox renders for a role-appropriate student fixture only '
      '(no office/admin transfer content ever appears)', (tester) async {
    await pumpMailbox(
      tester,
      notifications: [
        notificationJson(id: 'n-1', type: 'ticket_reply'),
        notificationJson(
          id: 'n-2',
          type: 'office_reassigned',
          title: 'Ticket TK-20261013-07BA4C reassigned',
          body: 'Your ticket was reassigned to Registrar.',
        ),
      ],
    );

    // Student-facing notification types render normally...
    expect(find.text('Ticket TK-20261013-07BA4C reassigned'), findsOneWidget);
    // ...and nothing from the office-only transfer vocabulary ever
    // appears, because the backend's own user_id-scoped query (see
    // list_notifications in ticket_notifications.py) never returns a
    // transfer_requested/transfer_accepted/transfer_rejected row -- or
    // any internal-note reply -- to a student's own feed in the first
    // place. This page has no transfer-specific code path to test here;
    // the guarantee is structural, not client-side filtering.
    expect(find.textContaining('transfer'), findsNothing);
    expect(find.textContaining('Internal'), findsNothing);
  });

  // --- Responsive header at required widths --------------------------------

  for (final width in <double>[360, 600, 900, 1400]) {
    testWidgets(
        'the mailbox header stays usable at width ${width.toInt()}px, no overflow',
        (tester) async {
      final unexpectedErrors = <String>[];
      final previousOnError = FlutterError.onError;
      FlutterError.onError = (details) {
        unexpectedErrors.add(details.toString());
        previousOnError?.call(details);
      };
      addTearDown(() => FlutterError.onError = previousOnError);

      await pumpMailbox(
        tester,
        size: Size(width, 900),
        notifications: [notificationJson(id: 'n-1')],
      );

      expect(unexpectedErrors, isEmpty);
      // At wide widths this legitimately matches twice: the header's own
      // "Mailbox" nav link (now active) plus this page's own title.
      expect(find.text('Mailbox'), findsWidgets);
      expect(find.text('Mark all read'), findsOneWidget);
      expect(find.text('New reply on TK-20261013-07BA4C'), findsOneWidget);
    });
  }
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
