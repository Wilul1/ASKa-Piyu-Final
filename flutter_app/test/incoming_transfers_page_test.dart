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

  Future<void> switchToOutgoing(WidgetTester tester) async {
    await tester.tap(find.text('Outgoing'));
    await tester.pumpAndSettle();
  }

  // --- Header -------------------------------------------------------------

  testWidgets('header shows the new title, subtitle, and unread badge',
      (tester) async {
    await pumpPage(tester, incoming: const []);

    expect(find.text('Office Mailbox'), findsOneWidget);
    expect(find.text('Manage ticket transfer requests'), findsOneWidget);
    // The same shared badge the sidebar/dashboard button already use --
    // never a separately-coded count.
    expect(find.byType(TransferBadge), findsWidgets);
  });

  testWidgets('no separate "Outgoing requests" action or distinct page title '
      'remain -- the segmented switch replaces both', (tester) async {
    await pumpPage(tester, incoming: const []);

    expect(find.text('Outgoing requests'), findsNothing);
    expect(find.text('Incoming Transfers'), findsNothing);
    expect(find.text('Outgoing Transfers'), findsNothing);
  });

  // --- Segmented switch -----------------------------------------------------

  testWidgets(
      'the Incoming/Outgoing switch lives inside the page -- selecting '
      'Outgoing never pushes a new page', (tester) async {
    await pumpPage(
      tester,
      incoming: [transferJson(id: 'tr-in', ticketId: 'TK-IN')],
      outgoing: [
        transferJson(
          id: 'tr-out',
          ticketId: 'TK-OUT',
          destinationOfficeName: 'Accounting Office',
        ),
      ],
    );

    expect(find.text('Incoming'), findsOneWidget);
    expect(find.text('Outgoing'), findsOneWidget);
    expect(find.text('Ticket #TK-IN'), findsOneWidget);
    expect(find.text('Ticket #TK-OUT'), findsNothing);

    await switchToOutgoing(tester);

    // Still the exact same page instance -- a tab switch, not a route push.
    expect(find.byType(IncomingTransfersPage), findsOneWidget);
    expect(find.text('Ticket #TK-OUT'), findsOneWidget);
    expect(find.text('Ticket #TK-IN'), findsNothing);

    await tester.tap(find.text('Incoming'));
    await tester.pumpAndSettle();

    expect(find.text('Ticket #TK-IN'), findsOneWidget);
    expect(find.text('Ticket #TK-OUT'), findsNothing);
  });

  // --- Inbox cards ----------------------------------------------------------

  testWidgets(
      'an incoming card shows the source office in bold, ticket reference, '
      'reason preview, and a status badge', (tester) async {
    await pumpPage(
      tester,
      incoming: [transferJson(id: 'tr-1')],
    );

    // The other office relative to the viewer is the "sender" line for an
    // incoming request -- the source office.
    expect(find.text('ICT Office'), findsOneWidget);
    expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);
    expect(
      find.text('Portal login issue is actually a records-correction request.'),
      findsOneWidget,
    );
    expect(find.text('Pending'), findsOneWidget);
    // Accept/Reject are not shown inline on the card -- only in the opened
    // details dialog (see below).
    expect(find.text('Accept'), findsNothing);
    expect(find.text('Reject'), findsNothing);
  });

  testWidgets(
      'an outgoing card shows the destination office in bold, never the '
      "viewer's own source office", (tester) async {
    await pumpPage(
      tester,
      outgoing: [
        transferJson(
          id: 'tr-1',
          sourceOfficeName: 'Registrar',
          destinationOfficeName: 'Accounting Office',
          status: 'Accepted',
          decidedByUserId: 'staff-2',
        ),
      ],
    );
    await switchToOutgoing(tester);

    expect(find.text('Accounting Office'), findsOneWidget);
    expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);
    expect(find.text('Accepted'), findsOneWidget);
  });

  testWidgets(
      'the mailbox shows a readable timestamp, never the raw ISO-8601 string',
      (tester) async {
    await pumpPage(
      tester,
      incoming: [transferJson(id: 'tr-1', createdAt: '2026-10-13T12:00:00Z')],
    );

    expect(find.textContaining('2026-10-13T12:00:00Z'), findsNothing);
    // The card uses the compact "Oct 13" form (see _formatRequestDateCompact
    // -- the full date+time form is too wide sharing a line with the other
    // office's name); the full "Oct 13, 2026, ..." form only appears once
    // the message is actually opened.
    expect(find.textContaining('Oct 13'), findsOneWidget);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();

    expect(find.textContaining('2026-10-13T12:00:00Z'), findsNothing);
    expect(find.textContaining('Oct 13, 2026'), findsOneWidget);
  });

  // --- Request details --------------------------------------------------

  testWidgets(
      'selecting an incoming mailbox card opens details with Accept and '
      'Reject for a pending request', (tester) async {
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();

    final dialog = find.byType(AlertDialog);
    expect(dialog, findsOneWidget);
    // Reading-pane header: the other office + "Ticket #X -> destination"
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

  testWidgets(
      'a decided (non-pending) incoming request\'s details show no Accept/Reject',
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
      'an outgoing request\'s details never show Accept/Reject, even while '
      'still Pending', (tester) async {
    await pumpPage(
      tester,
      outgoing: [transferJson(id: 'tr-1', status: 'Pending')],
    );
    await switchToOutgoing(tester);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    // The caller never decides their own sent request, regardless of its
    // status -- only the destination office does, from the Incoming tab.
    expect(find.widgetWithText(FilledButton, 'Accept'), findsNothing);
    expect(find.widgetWithText(TextButton, 'Reject'), findsNothing);
    expect(find.text('Close'), findsOneWidget);
  });

  // --- Empty states -------------------------------------------------------

  testWidgets(
      'empty incoming mailbox shows the new empty state with a link to Outgoing',
      (tester) async {
    await pumpPage(tester, incoming: const []);

    expect(find.text('Inbox is clear'), findsOneWidget);
    expect(
      find.text('New transfer requests from other offices will appear here.'),
      findsOneWidget,
    );
    final action = find.text('View outgoing requests');
    expect(action, findsOneWidget);

    await tester.tap(action);
    await tester.pumpAndSettle();

    // The action switches to the Outgoing tab in place.
    expect(find.text('No outgoing requests yet'), findsOneWidget);
  });

  testWidgets('empty outgoing view uses an outgoing-specific message',
      (tester) async {
    await pumpPage(tester, outgoing: const []);
    await switchToOutgoing(tester);

    expect(find.text('No outgoing requests yet'), findsOneWidget);
    expect(
      find.text(
        'Transfer requests your office sends to other offices will appear here.',
      ),
      findsOneWidget,
    );
    // Never the Incoming-specific wording.
    expect(find.text('Inbox is clear'), findsNothing);

    await tester.tap(find.text('View incoming requests'));
    await tester.pumpAndSettle();

    expect(find.text('Inbox is clear'), findsOneWidget);
  });

  // --- Responsive header/switch at required widths -------------------------
  //
  // OfficeScaffold/AdminScaffold are used with showHeader: false here (this
  // page builds its own header), so the previously-fixed shared-header
  // overflow doesn't apply directly -- but this page's own header (title +
  // badge + compact mark-read action) and segmented switch need the same
  // discipline, confirmed at the same width matrix used throughout this
  // app's other responsive-header tests.

  for (final width in <double>[360, 600, 900, 1400]) {
    testWidgets(
        'the mailbox header and switch never overflow at width '
        '${width.toInt()}px, and stay usable', (tester) async {
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
        outgoing: [transferJson(id: 'tr-2', ticketId: 'TK-OUT')],
      );
      expect(unexpectedErrors, isEmpty);
      // At narrow widths the page also has an AppBar with the same title
      // text, so this may legitimately match twice (AppBar + body header).
      expect(find.text('Office Mailbox'), findsWidgets);
      expect(find.text('Incoming'), findsOneWidget);
      expect(find.text('Outgoing'), findsOneWidget);
      expect(find.text('Mark all read'), findsOneWidget);
      expect(find.text('Ticket #TK-20260824-07BA4C'), findsOneWidget);

      await switchToOutgoing(tester);
      expect(unexpectedErrors, isEmpty);
      expect(find.text('Ticket #TK-OUT'), findsOneWidget);

      await tester.tap(find.text('Ticket #TK-OUT'));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);
      expect(unexpectedErrors, isEmpty);
    });
  }

  // Admin routes through AdminScaffold rather than OfficeScaffold (see
  // IncomingTransfersPage.build's isOffice branch) -- covered directly
  // since it's a separate scaffold, not relying on the office case above
  // to stand in for it.
  for (final width in <double>[360, 600, 900, 1400]) {
    testWidgets(
        'admin: the mailbox header and switch never overflow at width '
        '${width.toInt()}px', (tester) async {
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
      expect(find.text('Office Mailbox'), findsWidgets);
      expect(find.text('Mark all read'), findsOneWidget);
      expect(unexpectedErrors, isEmpty);
    });
  }

  // --- Mark-notifications-read ---------------------------------------------

  testWidgets(
      'the explicit mark-all-read action is visible and never automatic',
      (tester) async {
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);

    // It exists as a deliberate action the viewer must tap -- opening or
    // refreshing the mailbox alone never triggers it.
    expect(find.text('Mark all read'), findsOneWidget);
  });

  testWidgets('mark-all-read failure surfaces an error and resets the button',
      (tester) async {
    // No backend is reachable in this widget-test sandbox (resolvedApiBase
    // is empty outside release builds), so tapping this action
    // deterministically exercises its failure path.
    await pumpPage(tester, incoming: const []);

    await tester.tap(find.text('Mark all read'));
    await tester.pumpAndSettle();

    expect(find.text('Mark all read'), findsOneWidget);
    expect(find.byType(SnackBar), findsOneWidget);
  });

  testWidgets(
      'mark-all-read works the same way regardless of which tab is active',
      (tester) async {
    await pumpPage(tester, outgoing: const []);
    await switchToOutgoing(tester);

    await tester.tap(find.text('Mark all read'));
    await tester.pumpAndSettle();

    expect(find.text('Mark all read'), findsOneWidget);
    expect(find.byType(SnackBar), findsOneWidget);
  });

  testWidgets('mark-all-read action renders for admin too', (tester) async {
    await pumpPage(tester, user: adminUser(), incoming: const []);

    expect(find.text('Mark all read'), findsOneWidget);
  });

  // --- Role coverage --------------------------------------------------------

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

  // --- Accept/Reject failure paths and the per-id busy guard ---------------

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
    // existing reject flow); the failed request never removes the card.
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
  // _decide() guards per request id (a Set, not a single id) and clears
  // that guard in a finally block covering every exit path, including the
  // thrown-error branch. There is no HTTP-mocking seam in this codebase's
  // widget tests, and this sandbox's network failure resolves well within
  // a single dialog-close animation, so the busy spinner's own transient
  // on-screen frame cannot be deterministically captured here. What IS
  // verified below: the guard never leaves a request stuck disabled after
  // a failed decision (the finally-cleanup guarantee), and a decision on
  // one request never affects a different one (the per-id, not global,
  // guarantee).

  testWidgets(
      'a request remains fully usable again after a failed decision (busy guard clears in finally)',
      (tester) async {
    await pumpPage(tester, incoming: [transferJson(id: 'tr-1')]);

    await tester.tap(find.text('Ticket #TK-20260824-07BA4C'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Accept'));
    await tester.pumpAndSettle();

    // If the busy guard were stuck "on" after the failure, the card would
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
    // sidebar/dashboard badge already depends on.
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
  //
  // These three exercise TransferBadge's RouteAware visibility/refresh
  // mechanism itself (not anything page-specific), via whichever instance
  // happens to be mounted alongside IncomingTransfersPage. The office
  // sidebar no longer has one -- the Office Dashboard's Mailbox button is
  // the sole entry point now (see sidebar.dart's _OfficeDarkSidebar) -- so
  // these pump as admin instead, whose sidebar still carries its own
  // "Incoming Transfers" nav item and TransferBadge, untouched by that
  // removal and exercising the exact same shared widget/mechanism. This
  // page's own header also renders a TransferBadge now (see _MailboxHeader)
  // -- that instance is covered by the same mechanism and is additionally
  // exercised incidentally by every other test in this file that pumps the
  // page, but these three specifically need a stable, single, already-
  // proven-correct instance to assert the before/after delta against.

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
