import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/app_route_observer.dart';
import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/models/ticket_transfer_models.dart';
import 'package:aska_piyu/screens/incoming_transfers_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/widgets/sidebar.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Map<String, dynamic> transferJson({
    required String id,
    String ticketId = 'TK-20260824-07BA4C',
    String sourceOfficeId = 'office-ict',
    String sourceOfficeName = 'ICT Office',
    String destinationOfficeId = 'office-registrar',
    String destinationOfficeName = 'Registrar',
    String reason = 'Portal login issue is actually a records-correction request.',
    String status = 'Pending',
    String createdAt = '2026-10-13T12:00:00Z',
    String? decidedAt,
    String? decidedByUserId,
    String? rejectionReason,
  }) {
    return {
      'id': id,
      'ticket_id': ticketId,
      'source_office_id': sourceOfficeId,
      'source_office_name': sourceOfficeName,
      'destination_office_id': destinationOfficeId,
      'destination_office_name': destinationOfficeName,
      'initiated_by_user_id': 'user-1',
      'reason': reason,
      'status': status,
      'created_at': createdAt,
      'decided_at': decidedAt,
      'decided_by_user_id': decidedByUserId,
      'rejection_reason': rejectionReason,
    };
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

  AuthUser adminUser() {
    return const AuthUser(
      id: 'admin-1',
      email: 'admin@example.edu',
      fullName: 'ASKa Admin',
      role: 'admin',
      officeId: null,
      officeName: null,
      emailVerified: true,
      createdAt: null,
      updatedAt: null,
    );
  }

  Future<void> pumpPage(
    WidgetTester tester, {
    AuthUser? user,
    List<Map<String, dynamic>>? incoming,
    List<Map<String, dynamic>>? outgoing,
    Size size = const Size(1400, 1000),
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(service: _FakeAuthService(user ?? officeUser()));
    await controller.login(const LoginRequest(email: 'office@example.edu', password: 'password'));

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          navigatorObservers: [appRouteObserver],
          home: IncomingTransfersPage(
            debugIncoming: incoming ?? const [],
            debugOutgoing: outgoing ?? const [],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets(
      'incoming mailbox row renders source office, reason, and ticket reference',
      (tester) async {
    await pumpPage(
      tester,
      incoming: [
        transferJson(id: 'tr-1'),
      ],
    );

    expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);
    expect(find.text('From ICT Office'), findsOneWidget);
    expect(
      find.text('Portal login issue is actually a records-correction request.'),
      findsOneWidget,
    );
    // Accept/Reject are not shown inline on the row -- only in the opened
    // details dialog (see below).
    expect(find.text('Accept'), findsNothing);
    expect(find.text('Reject'), findsNothing);
  });

  testWidgets(
      'selecting a mailbox row opens details with Accept and Reject for a pending request',
      (tester) async {
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();

    final dialog = find.byType(AlertDialog);
    expect(dialog, findsOneWidget);
    expect(find.descendant(of: dialog, matching: find.text('From')), findsOneWidget);
    expect(find.descendant(of: dialog, matching: find.text('ICT Office')), findsOneWidget);
    expect(find.descendant(of: dialog, matching: find.text('To')), findsOneWidget);
    // The signed-in office user's own office is also named "Registrar" (see
    // officeUser() above) and may render elsewhere in the sidebar chrome
    // behind this dialog, so this is scoped to the dialog specifically.
    expect(find.descendant(of: dialog, matching: find.text('Registrar')), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Accept'), findsOneWidget);
    expect(find.widgetWithText(TextButton, 'Reject'), findsOneWidget);
  });

  testWidgets('a decided (non-pending) request\'s details show no Accept/Reject',
      (tester) async {
    await pumpPage(
      tester,
      incoming: [transferJson(id: 'tr-1', status: 'Accepted', decidedByUserId: 'staff-2')],
    );

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Accept'), findsNothing);
    expect(find.widgetWithText(TextButton, 'Reject'), findsNothing);
    expect(find.text('Close'), findsOneWidget);
  });

  testWidgets('empty incoming mailbox shows an empty state', (tester) async {
    await pumpPage(tester, incoming: const []);

    expect(find.text('No incoming transfer requests.'), findsOneWidget);
  });

  testWidgets('outgoing requests are reached via a separate page, not a tab',
      (tester) async {
    await pumpPage(
      tester,
      outgoing: [
        transferJson(id: 'tr-pending', status: 'Pending'),
        transferJson(id: 'tr-accepted', status: 'Accepted', decidedByUserId: 'staff-2'),
        transferJson(
          id: 'tr-rejected',
          status: 'Rejected',
          decidedByUserId: 'staff-2',
          rejectionReason: 'Not a records issue.',
        ),
      ],
    );

    // Never presented as a sibling tab next to the incoming mailbox.
    expect(find.text('Outgoing'), findsNothing);
    expect(find.text('Incoming'), findsNothing);

    await tester.tap(find.text('Outgoing requests'));
    await tester.pumpAndSettle();

    expect(find.text('Outgoing Transfers'), findsOneWidget);
    expect(find.text('Pending'), findsOneWidget);
    expect(find.text('Accepted'), findsOneWidget);
    expect(find.text('Rejected'), findsOneWidget);
    expect(find.text('Rejection reason: Not a records issue.'), findsOneWidget);
    // Outgoing requests never show Accept/Reject actions.
    expect(find.text('Accept'), findsNothing);
  });

  testWidgets('admin sees the incoming mailbox without an office account',
      (tester) async {
    await pumpPage(
      tester,
      user: adminUser(),
      incoming: [transferJson(id: 'tr-1')],
    );

    expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();

    expect(find.widgetWithText(FilledButton, 'Accept'), findsOneWidget);
  });

  testWidgets('accept failure keeps the request visible and shows one error',
      (tester) async {
    // No backend is reachable in this widget-test sandbox (resolvedApiBase
    // is empty outside release builds), so tapping Accept deterministically
    // exercises the failure path: the request stays visible and exactly one
    // error is surfaced, never a silent drop or a duplicate error.
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Accept'));
    await tester.pumpAndSettle();

    // The dialog closes immediately (optimistic hand-off, mirroring the
    // existing reject flow); the failed request never removes the row.
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);
    expect(find.byType(SnackBar), findsOneWidget);
  });

  testWidgets('reject failure keeps the request visible and shows an error',
      (tester) async {
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Reject'));
    await tester.pumpAndSettle();
    // The confirmation dialog appears; confirm without typing a reason.
    expect(find.text('Reject transfer request'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Reject'));
    await tester.pumpAndSettle();

    expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);
    expect(find.byType(SnackBar), findsOneWidget);
  });

  // --- duplicate accept/reject protection ---------------------------------
  //
  // _decide() now guards per request id (a Set, not a single id) and clears
  // that guard in a finally block covering every exit path, including the
  // thrown-error branch. There is no HTTP-mocking seam in this codebase's
  // widget tests, and this sandbox's network failure resolves well within
  // a single dialog-close animation (confirmed by direct frame-by-frame
  // inspection: the failure SnackBar is already showing before the dialog
  // even finishes closing), so the busy spinner's own transient on-screen
  // frame cannot be deterministically captured here -- exactly the same
  // documented limitation this file already states for the badge-refresh
  // tick above. What IS verified below: the guard never leaves a request
  // stuck disabled after a failed decision (the finally-cleanup guarantee),
  // and a decision on one request never affects a different one (the
  // per-id, not global, guarantee).

  testWidgets(
      'a request remains fully usable again after a failed decision (busy guard clears in finally)',
      (tester) async {
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Accept'));
    await tester.pumpAndSettle();

    // If the busy guard were stuck "on" after the failure, the row would
    // stay disabled and this second attempt would silently do nothing.
    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Accept'), findsOneWidget);
  });

  testWidgets(
      'deciding one request never disables a different, unrelated request',
      (tester) async {
    await pumpPage(
      tester,
      incoming: [
        transferJson(id: 'tr-1', ticketId: 'TK-FIRST'),
        transferJson(id: 'tr-2', ticketId: 'TK-SECOND'),
      ],
    );

    await tester.tap(find.text('Ticket #TK-FIRST'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Accept'));
    await tester.pumpAndSettle();

    // tr-1's failed decision must never have touched tr-2's own usability.
    await tester.tap(find.text('Ticket #TK-SECOND'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Accept'), findsOneWidget);
    expect(find.widgetWithText(TextButton, 'Reject'), findsOneWidget);
  });

  testWidgets(
      'unread badge wiring (transferBadgeRefreshTick) is untouched by the mailbox decision flow',
      (tester) async {
    // There is no HTTP-mocking seam in this codebase's widget tests (every
    // network call here deterministically fails), so a *successful*
    // decision's badge-refresh effect can never be exercised directly --
    // see the same documented limitation below for the sidebar's own
    // badge tests. What IS verifiable here: completing the mailbox's
    // reject flow (dialog -> reason prompt -> confirm) runs to completion
    // without disturbing the existing tick-based refresh mechanism the
    // sidebar badge already depends on.
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);
    final before = transferBadgeRefreshTick.value;

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Reject'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Reject'));
    await tester.pumpAndSettle();

    // The failure path (no reachable backend) does not bump the tick --
    // only a successful decision does (see IncomingTransfersPage._decide).
    // This asserts that running the full dialog flow didn't throw or
    // otherwise corrupt the notifier, which a crash would have prevented.
    expect(transferBadgeRefreshTick.value, before);
  });

  testWidgets('the explicit mark-notifications-read action is visible and never automatic',
      (tester) async {
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);

    // It exists as a deliberate action the viewer must tap -- opening or
    // refreshing the mailbox alone never triggers it.
    expect(find.text('Mark notifications read'), findsOneWidget);
  });

  testWidgets('mark-notifications-read failure surfaces an error and resets the button',
      (tester) async {
    // Same reasoning as the accept/reject failure tests: no backend is
    // reachable in this sandbox, so tapping this action deterministically
    // exercises its failure path.
    await pumpPage(tester, incoming: const []);

    await tester.tap(find.text('Mark notifications read'));
    await tester.pumpAndSettle();

    expect(find.text('Mark notifications read'), findsOneWidget);
    expect(find.byType(SnackBar), findsOneWidget);
  });

  testWidgets('mark-notifications-read action renders for admin too', (tester) async {
    await pumpPage(tester, user: adminUser(), incoming: const []);

    expect(find.text('Mark notifications read'), findsOneWidget);
  });

  // --- badge route-visibility (does a hidden page's badge refetch?) -------
  //
  // There is no HTTP-mocking seam in this codebase's widget tests (every
  // network call here deterministically fails -- resolvedApiBase is empty
  // outside release builds), so a fetch's only *successful* observable
  // effect (updating the rendered count) can never be exercised here. The
  // only way to tell "a fetch was attempted" from "it was correctly
  // skipped" is the test-only debugTransferBadgeLoadAttempts counter in
  // sidebar.dart, bumped at the top of _TransferBadge._load() regardless
  // of whether the subsequent network call succeeds or fails. These tests
  // read it as a before/after delta, never an absolute value, since other
  // tests in this file may have already incremented it.

  Future<void> pushCover(WidgetTester tester) async {
    final context = tester.element(find.byType(IncomingTransfersPage));
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (coverContext) => Scaffold(
          body: Center(
            child: ElevatedButton(
              onPressed: () => Navigator.of(coverContext).pop(),
              child: const Text('Close cover'),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('a visible badge refreshes when the refresh tick changes', (tester) async {
    await pumpPage(tester, incoming: const []);
    final before = debugTransferBadgeLoadAttempts;

    transferBadgeRefreshTick.value++;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(debugTransferBadgeLoadAttempts, greaterThan(before));
  });

  testWidgets('a covered badge does not refetch when the refresh tick changes while hidden',
      (tester) async {
    await pumpPage(tester, incoming: const []);
    await pushCover(tester);
    final whileCovered = debugTransferBadgeLoadAttempts;

    transferBadgeRefreshTick.value++;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(debugTransferBadgeLoadAttempts, whileCovered);
  });

  testWidgets('returning to a previously covered page refreshes its badge', (tester) async {
    await pumpPage(tester, incoming: const []);
    await pushCover(tester);
    final whileCovered = debugTransferBadgeLoadAttempts;

    await tester.tap(find.text('Close cover'));
    await tester.pumpAndSettle();

    expect(debugTransferBadgeLoadAttempts, greaterThan(whileCovered));
  });

  testWidgets('countUnreadTransferNotifications excludes unrelated and already-read items',
      (tester) async {
    final items = [
      {'type': 'transfer_requested', 'is_read': false},
      {'type': 'transfer_accepted', 'is_read': false},
      {'type': 'transfer_rejected', 'is_read': true}, // read -- excluded
      {'type': 'ticket_assigned', 'is_read': false}, // ambiguous -- excluded
      {'type': 'office_reassigned', 'is_read': false}, // ambiguous -- excluded
      {'type': 'ticket_reply', 'is_read': false}, // unrelated -- excluded
    ];

    expect(countUnreadTransferNotifications(items), 2);
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
