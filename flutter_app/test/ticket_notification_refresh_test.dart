import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/models/ticket_notification_models.dart';
import 'package:aska_piyu/screens/my_tickets_page.dart';
import 'package:aska_piyu/screens/student_mailbox_page.dart';
import 'package:aska_piyu/services/auth_service.dart';

/// Covers the fix for: Student Mailbox marking notifications read did not
/// refresh MyTicketsPage's own, separately-fetched notification banner/
/// count, which would otherwise only catch up on its own 8-second poll.
/// See ticketNotificationRefreshTick's own doc comment in
/// ticket_notification_models.dart.
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

  Map<String, dynamic> notificationJson({required String id, bool isRead = false}) {
    return {
      'id': id,
      'ticket_id': 'TK-20261013-07BA4C',
      'type': 'ticket_reply',
      'title': 'New reply on TK-20261013-07BA4C',
      'body': 'The Registrar replied to your ticket.',
      'is_read': isRead,
      'created_at': '2026-10-13T12:00:00Z',
    };
  }

  Future<AuthController> buildLoggedInController() async {
    final controller = AuthController(service: _FakeAuthService(studentUser()));
    await controller.login(
      const LoginRequest(email: 'student@example.edu', password: 'password'),
    );
    return controller;
  }

  // --- Consumer side: MyTicketsPage reacts to the shared tick -------------

  testWidgets(
      'MyTicketsPage refreshes its own notifications when '
      'ticketNotificationRefreshTick changes while mounted', (tester) async {
    final controller = await buildLoggedInController();

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: const MaterialApp(home: MyTicketsPage()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    final before = debugTicketNotificationRefreshAttempts;

    ticketNotificationRefreshTick.value++;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(debugTicketNotificationRefreshAttempts, greaterThan(before));
    // The listener ran without throwing -- no reachable backend in this
    // sandbox, so the fetch itself fails, but that failure must stay
    // silent (MyTicketsPage's existing _loadNotifications(silent: true)
    // behavior), never crashing the page.
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'a disposed MyTicketsPage does not react to the tick (listener '
      'correctly removed, no leak/crash)', (tester) async {
    final controller = await buildLoggedInController();

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: const MaterialApp(home: MyTicketsPage()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    // Replace MyTicketsPage with something else entirely, disposing it.
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: const MaterialApp(home: Scaffold(body: SizedBox())),
      ),
    );
    await tester.pump();

    final before = debugTicketNotificationRefreshAttempts;
    ticketNotificationRefreshTick.value++;
    await tester.pump();

    // The disposed page's listener must not still be registered -- the
    // counter (bumped only from that listener) stays unchanged.
    expect(debugTicketNotificationRefreshAttempts, before);
    expect(tester.takeException(), isNull);
  });

  // --- Producer side: StudentMailboxPage's own wiring, failure path -------
  //
  // There is no HTTP-mocking seam in this codebase's widget tests (every
  // network call here deterministically fails -- resolvedApiBase is empty
  // outside release builds), so the *successful* mark-read branch that
  // actually bumps ticketNotificationRefreshTick can never be exercised
  // directly here -- the same documented limitation already stated for
  // transferBadgeRefreshTick's own tests. What IS verified below: running
  // the full mark-all-read flow against the unreachable backend completes
  // without throwing and, since it fails, never bumps the tick -- matching
  // _markAllRead's own code path (the bump sits after `await _load()`,
  // reached only once `result.ok` is true).

  testWidgets(
      'a failed mark-all-read in the Mailbox never bumps the shared tick',
      (tester) async {
    final controller = await buildLoggedInController();

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: StudentMailboxPage(
            debugNotifications: [notificationJson(id: 'n-1', isRead: false)],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    final before = ticketNotificationRefreshTick.value;

    await tester.tap(find.widgetWithText(TextButton, 'Mark all read'));
    await tester.pumpAndSettle();

    expect(ticketNotificationRefreshTick.value, before);
    expect(find.byType(SnackBar), findsOneWidget);
  });

  testWidgets(
      'a failed per-notification open in the Mailbox never bumps the '
      'shared tick', (tester) async {
    final controller = await buildLoggedInController();

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: StudentMailboxPage(
            debugNotifications: [notificationJson(id: 'n-1', isRead: false)],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    final before = ticketNotificationRefreshTick.value;

    await tester.tap(find.text('New reply on TK-20261013-07BA4C'));
    await tester.pumpAndSettle();

    // The mark-read PATCH itself also fails in this sandbox, so neither
    // the local isRead update nor the tick bump happen -- confirmed by
    // the tick being unchanged. The user-visible failure is a SnackBar,
    // not a crash.
    expect(ticketNotificationRefreshTick.value, before);
    expect(find.byType(SnackBar), findsOneWidget);
    expect(tester.takeException(), isNull);
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
