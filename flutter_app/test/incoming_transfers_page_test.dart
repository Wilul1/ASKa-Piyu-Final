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

    // Inbox ordering: the source office is the "sender" line (no "From "
    // prefix -- that reads more like a form field than an inbox), ticket
    // reference moved to the row's metadata line.
    expect(find.text('ICT Office'), findsOneWidget);
    expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);
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
    // Reading-pane header: sender office + "Ticket #X -> destination"
    // subtitle, never a bare "From"/"To" form-field label.
    expect(find.descendant(of: dialog, matching: find.text('ICT Office')), findsOneWidget);
    expect(
      find.descendant(
        of: dialog,
        matching: find.textContaining('Ticket #TK-20260824-07BA4C'),
      ),
      findsOneWidget,
    );
    // The signed-in office user's own office is also named "Registrar" (see
    // officeUser() above) and may render elsewhere in the sidebar chrome
    // behind this dialog, so this is scoped to the dialog specifically.
    expect(
      find.descendant(of: dialog, matching: find.textContaining('Registrar')),
      findsOneWidget,
    );
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

  testWidgets(
      'the mailbox shows a readable timestamp, never the raw ISO-8601 string',
      (tester) async {
    await pumpPage(
      tester,
      incoming: [transferJson(id: 'tr-1', createdAt: '2026-10-13T12:00:00Z')],
    );

    expect(find.textContaining('2026-10-13T12:00:00Z'), findsNothing);
    // The row uses the compact "Oct 13" form (see _formatRequestDateCompact
    // -- the full date+time form is too wide sharing a line with the
    // sender name); the full "Oct 13, 2026, ..." form only appears once
    // the message is actually opened.
    expect(find.textContaining('Oct 13'), findsOneWidget);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();

    expect(find.textContaining('2026-10-13T12:00:00Z'), findsNothing);
    expect(find.textContaining('Oct 13, 2026'), findsOneWidget);
  });

  // OfficeScaffold/AdminScaffold's shared header Row (title/description +
  // the "Outgoing requests" and "Mark notifications read" actions, spread
  // in unwrapped with no Expanded/Wrap around the action buttons) used to
  // RenderFlex-overflow at narrower widths -- now fixed in
  // office_scaffold.dart / admin_scaffold.dart via a responsive header that
  // wraps actions onto their own line below the title once they no longer
  // fit on one line. This page -- with two real header actions on both its
  // Incoming and Outgoing views -- is exactly the case that used to
  // overflow, so it covers the fix across the narrow/Drawer width (360),
  // just-below-desktop widths (600, 900), and a comfortably wide desktop
  // width, asserting no overflow anywhere AND that both actions stay
  // genuinely available (findable), never clipped or hidden, at every one.
  for (final width in <double>[360, 600, 900, 1400]) {
    testWidgets(
        'the header and mailbox never overflow at width ${width.toInt()}px, '
        'and both header actions stay available',
        (tester) async {
      final unexpectedErrors = <String>[];
      final previousOnError = FlutterError.onError;
      FlutterError.onError = (details) {
        unexpectedErrors.add(details.toString());
        previousOnError?.call(details);
      };
      addTearDown(() => FlutterError.onError = previousOnError);

      await pumpPage(
        tester,
        size: Size(width, 900),
        incoming: [transferJson(id: 'tr-1')],
      );
      expect(unexpectedErrors, isEmpty);
      expect(find.text('Outgoing requests'), findsOneWidget);
      expect(find.text('Mark notifications read'), findsOneWidget);
      expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);

      await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsOneWidget);
      expect(unexpectedErrors, isEmpty);

      await tester.tap(find.text('Close'));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Outgoing requests'));
      await tester.pumpAndSettle();

      // At narrow widths the page also has an AppBar with the same title
      // text, so this may legitimately match twice (AppBar + body header).
      expect(find.text('Outgoing Transfers'), findsWidgets);
      expect(find.text('Mark notifications read'), findsOneWidget);
      expect(unexpectedErrors, isEmpty);
    });
  }

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

  // --- stale badge root cause: "Mark notifications read" must also exist
  // on the Outgoing page ------------------------------------------------
  //
  // Root cause of the reported production bug: accept_ticket_transfer /
  // reject_ticket_transfer (backend/app/services/ticketing.py) create a
  // new, unread "transfer_accepted"/"transfer_rejected" notification for
  // the SOURCE office -- the office that sent the request, not the one
  // that decided it. The only thing that ever auto-marks-read server-side
  // is the DESTINATION office's own "transfer_requested" notification (the
  // scoped UPDATE in both functions, keyed by transfer_request_id). A pure
  // source office -- one with nothing pending to decide -- has no reason
  // to ever open the Incoming mailbox, so the explicit "Mark notifications
  // read" action living only there was never reachable for the exact
  // notification type keeping their badge non-zero. The fix adds the same
  // explicit action to the Outgoing page, which is where a source office
  // actually goes to see that its request was decided.

  testWidgets(
      'the Outgoing page also offers the explicit mark-notifications-read action',
      (tester) async {
    await pumpPage(
      tester,
      outgoing: [transferJson(id: 'tr-1', status: 'Accepted', decidedByUserId: 'staff-2')],
    );

    await tester.tap(find.text('Outgoing requests'));
    await tester.pumpAndSettle();

    expect(find.text('Outgoing Transfers'), findsOneWidget);
    // It exists as a deliberate action the viewer must tap, exactly
    // mirroring the Incoming page's own action -- never triggered just by
    // viewing the resolved outgoing request.
    expect(find.text('Mark notifications read'), findsOneWidget);
  });

  testWidgets(
      'mark-notifications-read on the Outgoing page surfaces an error and resets the button',
      (tester) async {
    // Same reasoning as the Incoming page's own failure-path tests: no
    // backend is reachable in this sandbox, so tapping this action
    // deterministically exercises its failure path.
    await pumpPage(tester, outgoing: const []);

    await tester.tap(find.text('Outgoing requests'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Mark notifications read'));
    await tester.pumpAndSettle();

    expect(find.text('Mark notifications read'), findsOneWidget);
    expect(find.byType(SnackBar), findsOneWidget);
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

  // Admin routes through AdminScaffold rather than OfficeScaffold (see
  // IncomingTransfersPage's isOffice branch) -- a separate, independently
  // duplicated _ResponsiveHeader in admin_scaffold.dart, so this covers
  // that copy directly rather than relying on OfficeScaffold's coverage
  // above to stand in for it.
  for (final width in <double>[360, 600, 900, 1400]) {
    testWidgets(
        'admin: the header and mailbox never overflow at width '
        '${width.toInt()}px, and both header actions stay available',
        (tester) async {
      final unexpectedErrors = <String>[];
      final previousOnError = FlutterError.onError;
      FlutterError.onError = (details) {
        unexpectedErrors.add(details.toString());
        previousOnError?.call(details);
      };
      addTearDown(() => FlutterError.onError = previousOnError);

      await pumpPage(
        tester,
        user: adminUser(),
        size: Size(width, 900),
        incoming: [transferJson(id: 'tr-1')],
      );
      expect(unexpectedErrors, isEmpty);
      expect(find.text('Outgoing requests'), findsOneWidget);
      expect(find.text('Mark notifications read'), findsOneWidget);

      await tester.tap(find.text('Outgoing requests'));
      await tester.pumpAndSettle();

      expect(find.text('Outgoing Transfers'), findsWidgets);
      expect(find.text('Mark notifications read'), findsOneWidget);
      expect(unexpectedErrors, isEmpty);
    });
  }

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
  // sidebar.dart, bumped at the top of TransferBadge._load() regardless
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

  // These three exercise TransferBadge's RouteAware visibility/refresh
  // mechanism itself (not anything page-specific), via whichever instance
  // happens to be mounted alongside IncomingTransfersPage. The office
  // sidebar no longer has one -- the Office Dashboard's Mailbox button
  // is the sole entry point now (see sidebar.dart's _OfficeDarkSidebar) --
  // so these pump as admin instead, whose sidebar still carries its own
  // "Incoming Transfers" nav item and TransferBadge, untouched by that
  // removal and exercising the exact same shared widget/mechanism.

  testWidgets('a visible badge refreshes when the refresh tick changes', (tester) async {
    await pumpPage(tester, user: adminUser(), incoming: const []);
    final before = debugTransferBadgeLoadAttempts;

    transferBadgeRefreshTick.value++;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(debugTransferBadgeLoadAttempts, greaterThan(before));
  });

  testWidgets('a covered badge does not refetch when the refresh tick changes while hidden',
      (tester) async {
    await pumpPage(tester, user: adminUser(), incoming: const []);
    await pushCover(tester);
    final whileCovered = debugTransferBadgeLoadAttempts;

    transferBadgeRefreshTick.value++;
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(debugTransferBadgeLoadAttempts, whileCovered);
  });

  testWidgets('returning to a previously covered page refreshes its badge', (tester) async {
    await pumpPage(tester, user: adminUser(), incoming: const []);
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
