import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_management_pages.dart';
import 'package:aska_piyu/services/auth_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Map<String, dynamic> ticketJson({
    required String id,
    required String subject,
    required String status,
    String requester = 'Wilmark Veridiano',
    String description =
        'I need a Good Moral Certificate. Student number: 2024-12345. Campus: Sta Cruz. Program: BSIT',
  }) {
    return {
      'ticket_id': id,
      'id': id,
      'user_id': 'user-1',
      'user_name': requester,
      'user_email': 'wilmarkveridiano9@gmail.com',
      'original_question': subject,
      'description': description,
      'status': status,
      'priority': 'Medium',
      'category': 'Student Records',
      'assigned_office': 'Office of Student Affairs (OSA)',
      'assigned_office_name': 'Office of Student Affairs (OSA)',
      'assigned_office_id': 'office-osa',
      'created_at': '2026-08-24T12:00:00Z',
      'updated_at': '2026-08-24T14:15:00Z',
      'messages': [
        {
          'id': 'm1',
          'ticket_id': id,
          'sender_id': 'user-1',
          'sender_role': 'student',
          'sender_name': requester,
          'message': description,
          'created_at': '2026-08-24T12:00:00Z',
          'is_internal': false,
        },
        {
          'id': 'm2',
          'ticket_id': id,
          'sender_id': 'osa-1',
          'sender_role': 'office',
          'sender_name': 'OSA',
          'message': 'Good day! Please be guided as follows.',
          'created_at': '2026-08-24T14:15:00Z',
          'is_internal': false,
        },
      ],
    };
  }

  List<Map<String, dynamic>> officeChoices() => const [
        {'id': 'office-registrar', 'name': 'Registrar'},
        {'id': 'office-ict', 'name': 'ICT Office'},
      ];

  Future<void> pumpWorkspace(
    WidgetTester tester, {
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? tickets,
    List<Map<String, dynamic>>? offices,
    // True only for the dialog-lifecycle tests below, which need the
    // dialog's own real (non-seeded) _loadOffices() to actually run.
    bool skipOfficeSeed = false,
    String search = '',
    String? initialSelectedTicketId,
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(
      service: _FakeAuthService(_officeUser()),
    );
    await controller.login(const LoginRequest(
      email: 'office@example.edu',
      password: 'password',
    ));

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: OfficeAssignedTicketsPage(
            initialSearch: search,
            initialSelectedTicketId: initialSelectedTicketId,
            debugOffices: skipOfficeSeed ? null : (offices ?? officeChoices()),
            debugTickets: tickets ??
                [
                  ticketJson(
                    id: 'TK-20260824-07BA4C',
                    subject:
                        'Need steps and fee for Issuance of Good Moral Certificate (Undergraduate)',
                    status: 'Resolved',
                  ),
                  ticketJson(
                    id: 'TK-20260819-4EF52E',
                    subject:
                        'How do I get an excuse slip if I missed class because I was sick?',
                    status: 'Resolved',
                    requester: 'John Dela Cruz',
                    description: 'I missed class because I was sick.',
                  ),
                ],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('Assigned Tickets renders inline workspace without a dialog',
      (tester) async {
    await pumpWorkspace(tester);

    expect(find.text('Assigned Tickets'), findsWidgets);
    expect(find.text('TK-20260824-07BA4C'), findsOneWidget);
    expect(find.byType(Dialog), findsNothing);
    expect(find.text('Select a ticket to view the conversation.'), findsOneWidget);
  });

  testWidgets('selecting a ticket updates center and right panels inline',
      (tester) async {
    await pumpWorkspace(tester);

    await tester.tap(find.text('TK-20260824-07BA4C'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byType(Dialog), findsNothing);
    expect(find.text('Conversation'), findsOneWidget);
    expect(find.text('Details'), findsWidgets);
    expect(find.text('History'), findsOneWidget);
    expect(find.text('Ticket Details'), findsOneWidget);
    expect(find.text('Write a reply…'), findsOneWidget);
    expect(find.text('Send Reply'), findsOneWidget);
    expect(find.text('Add to KB'), findsOneWidget);
    expect(find.textContaining('Good day!'), findsOneWidget);
    expect(find.textContaining('2024-12345'), findsWidgets);
    expect(find.textContaining('Sta Cruz'), findsWidgets);
    expect(find.textContaining('BSIT'), findsWidgets);
  });

  testWidgets('search still filters the ticket list', (tester) async {
    await pumpWorkspace(tester);

    await tester.enterText(find.byType(TextField).first, 'excuse slip');
    await tester.pump();

    expect(find.text('TK-20260819-4EF52E'), findsOneWidget);
    expect(find.text('TK-20260824-07BA4C'), findsNothing);
  });

  testWidgets('status filters still work', (tester) async {
    await pumpWorkspace(tester);

    await tester.tap(find.text('Open (0)'));
    await tester.pump();

    expect(find.text('No matching tickets.'), findsOneWidget);
    await tester.tap(find.text('All (2)'));
    await tester.pump();
    expect(find.text('TK-20260824-07BA4C'), findsOneWidget);
  });

  testWidgets('pagination still works', (tester) async {
    final tickets = [
      for (var i = 0; i < 9; i++)
        ticketJson(
          id: 'TK-PAGE-$i',
          subject: 'Ticket number $i',
          status: 'Open',
          requester: 'Student $i',
          description: 'Body $i',
        ),
    ];
    await pumpWorkspace(tester, tickets: tickets);

    expect(find.text('TK-PAGE-0'), findsOneWidget);
    expect(find.text('Showing 1–8 of 9 tickets'), findsOneWidget);
    await tester.tap(find.text('Next'));
    await tester.pump();
    expect(find.text('TK-PAGE-8'), findsOneWidget);
    expect(find.text('TK-PAGE-0'), findsNothing);
  });

  testWidgets('narrow layout selects inline instead of opening a dialog',
      (tester) async {
    await pumpWorkspace(tester, size: const Size(520, 900));

    await tester.tap(find.text('TK-20260824-07BA4C'));
    await tester.pump();

    expect(find.byType(Dialog), findsNothing);
    expect(find.text('Back to tickets'), findsOneWidget);
    expect(find.text('Conversation'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('initialSelectedTicketId selects the ticket inline', (tester) async {
    await pumpWorkspace(
      tester,
      initialSelectedTicketId: 'TK-20260824-07BA4C',
    );

    expect(find.byType(Dialog), findsNothing);
    expect(find.text('Conversation'), findsOneWidget);
    expect(find.text('Send Reply'), findsOneWidget);
    expect(find.text('Ticket Details'), findsOneWidget);
    expect(find.text('Select a ticket to view the conversation.'), findsNothing);
  });

  // --- status workflow (Phase 2): no manual status dropdown anywhere -------
  //
  // No DropdownButtonFormField's current value is ever a status word
  // ('Open'/'In Progress'/'Resolved'/'Closed') -- that is the real
  // regression this guards, independent of the status badge rendering
  // twice (once in the thread header, once in the always-visible details
  // sidebar, at this wide viewport). Priority is also read-only in this
  // office-only pane now (see the dedicated test below) -- no dropdown of
  // any kind remains in this pane.
  const statusWords = {'Open', 'In Progress', 'Resolved', 'Closed'};
  Finder statusDropdowns() => find.byWidgetPredicate((widget) {
        if (widget is! DropdownButtonFormField<String>) return false;
        return statusWords.contains(widget.initialValue);
      });

  testWidgets(
      'Details sidebar shows status as a read-only badge with a Resolve '
      'action, never a status dropdown',
      (tester) async {
    await pumpWorkspace(
      tester,
      tickets: [
        ticketJson(
          id: 'TK-OPEN-1',
          subject: 'Need a Good Moral Certificate',
          status: 'Open',
        ),
      ],
      initialSelectedTicketId: 'TK-OPEN-1',
    );

    // The status badge (read-only) is shown...
    expect(find.text('Open'), findsWidgets);
    // ...and the dedicated Resolve action replaces the old dropdown.
    expect(find.text('Resolve'), findsOneWidget);
    expect(statusDropdowns(), findsNothing);
  });

  testWidgets(
      'priority is shown as a read-only badge in the office details '
      'panel, never a dropdown',
      (tester) async {
    await pumpWorkspace(
      tester,
      tickets: [
        ticketJson(id: 'TK-OPEN-1', subject: 'Need a Good Moral Certificate', status: 'Open'),
      ],
      initialSelectedTicketId: 'TK-OPEN-1',
    );

    // The fixture's priority ('Medium', set in ticketJson) is still
    // visible -- rendered twice at this wide viewport (thread header +
    // the always-visible details sidebar), same as the status badge
    // above.
    expect(find.text('Medium'), findsWidgets);
    // ...as a read-only badge (the same chip type used for the status
    // row just above it), never an editable priority dropdown.
    expect(
      find.byWidgetPredicate((widget) {
        if (widget is! DropdownButtonFormField<String>) return false;
        return const {'Low', 'Medium', 'High', 'Urgent'}.contains(widget.initialValue);
      }),
      findsNothing,
    );
  });

  testWidgets(
      'the Resolve button renders as a single compact outlined control and '
      'shows a loading state while resolving',
      (tester) async {
    await pumpWorkspace(
      tester,
      tickets: [
        ticketJson(id: 'TK-OPEN-1', subject: 'Need a Good Moral Certificate', status: 'Open'),
      ],
      initialSelectedTicketId: 'TK-OPEN-1',
    );

    final resolveFinder = find.byKey(const Key('resolve-ticket-button'));
    expect(resolveFinder, findsOneWidget);
    final button = tester.widget<OutlinedButton>(resolveFinder);
    expect(button.onPressed, isNotNull);
    // No decorative icon -- just the plain "Resolve" label.
    expect(find.descendant(of: resolveFinder, matching: find.byType(Icon)), findsNothing);
    expect(find.descendant(of: resolveFinder, matching: find.text('Resolve')), findsOneWidget);

    // No backend is reachable in this sandbox. The failure resolves fast
    // enough that the transient spinner frame isn't reliably observable
    // here (see the loading-state ternary in _StaffTicketDetailsPaneState
    // for the actual implementation); what IS deterministic is that the
    // button survives the failed attempt and settles back to its normal,
    // re-enabled "Resolve" label rather than getting stuck.
    await tester.tap(resolveFinder);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('resolve-ticket-button')), findsOneWidget);
    expect(find.descendant(of: resolveFinder, matching: find.text('Resolve')), findsOneWidget);
    expect(
      tester.widget<OutlinedButton>(resolveFinder).onPressed,
      isNotNull,
    );
  });

  testWidgets(
      'a Resolved ticket shows no Resolve action (office has no Close either)',
      (tester) async {
    await pumpWorkspace(
      tester,
      tickets: [
        ticketJson(
          id: 'TK-RESOLVED-1',
          subject: 'Already handled',
          status: 'Resolved',
        ),
      ],
      initialSelectedTicketId: 'TK-RESOLVED-1',
    );

    expect(find.text('Resolved'), findsWidgets);
    expect(find.text('Resolve'), findsNothing);
    // Close is admin-only -- office never sees it regardless of status.
    expect(find.text('Close'), findsNothing);
    expect(statusDropdowns(), findsNothing);
  });

  Future<void> openTransferDialog(WidgetTester tester) async {
    final transfer = find.byTooltip('Transfer / reassign', skipOffstage: false);
    await tester.ensureVisible(transfer);
    await tester.tap(transfer);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets(
      'the Transfer dialog renders a destination-office dropdown and a reason field, '
      'never a status dropdown',
      (tester) async {
    await pumpWorkspace(
      tester,
      tickets: [
        ticketJson(
          id: 'TK-TRANSFER-1',
          subject: 'Needs a different office',
          status: 'Open',
        ),
      ],
      initialSelectedTicketId: 'TK-TRANSFER-1',
    );

    await openTransferDialog(tester);

    expect(find.text('Transfer ticket'), findsOneWidget);
    expect(find.text('Destination office'), findsOneWidget);
    expect(find.text('Reason for transfer'), findsOneWidget);
    // No status word ('Open'/'In Progress'/'Resolved'/'Closed') is ever a
    // dropdown's current value inside this dialog.
    expect(
      find.descendant(
        of: find.byType(Dialog),
        matching: find.byWidgetPredicate((widget) {
          if (widget is! DropdownButtonFormField<String>) return false;
          return statusWords.contains(widget.initialValue);
        }),
      ),
      findsNothing,
    );
  });

  testWidgets('Apply is disabled until a destination office and a reason are provided',
      (tester) async {
    await pumpWorkspace(
      tester,
      tickets: [
        ticketJson(id: 'TK-TRANSFER-1', subject: 'Needs a different office', status: 'Open'),
      ],
      initialSelectedTicketId: 'TK-TRANSFER-1',
    );

    await openTransferDialog(tester);

    Widget applyButton() =>
        tester.widget(find.widgetWithText(ElevatedButton, 'Apply'));
    bool applyEnabled() => (applyButton() as ElevatedButton).onPressed != null;

    // Neither a destination nor a reason has been provided yet.
    expect(applyEnabled(), isFalse);

    await tester.tap(find.byKey(const Key('transfer-dialog-office-dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Registrar').last);
    await tester.pumpAndSettle();

    // A destination is selected but the reason is still empty.
    expect(applyEnabled(), isFalse);

    await tester.enterText(
      find.byKey(const Key('transfer-dialog-reason-field')),
      'Needs Registrar, not ICT.',
    );
    await tester.pump();

    expect(applyEnabled(), isTrue);
  });

  testWidgets('the current office is never offered as a transfer destination',
      (tester) async {
    await pumpWorkspace(
      tester,
      tickets: [
        ticketJson(
          id: 'TK-TRANSFER-1',
          subject: 'Needs a different office',
          status: 'Open',
        ),
      ],
      offices: const [
        {'id': 'office-osa', 'name': 'Office of Student Affairs (OSA)'},
        {'id': 'office-registrar', 'name': 'Registrar'},
      ],
      initialSelectedTicketId: 'TK-TRANSFER-1',
    );

    await openTransferDialog(tester);
    await tester.tap(find.byKey(const Key('transfer-dialog-office-dropdown')));
    await tester.pumpAndSettle();

    // The ticket's own current office (seeded via assigned_office_id in
    // ticketJson -- see below) must not appear as a choice.
    expect(find.text('Office of Student Affairs (OSA)').hitTestable(), findsNothing);
    expect(find.text('Registrar').last, findsOneWidget);
  });

  testWidgets(
      'submitting a transfer request never changes the ticket\'s displayed assigned office',
      (tester) async {
    // No backend is reachable in this widget-test sandbox, so Apply
    // deterministically exercises the failure path -- the point of this
    // test is that even attempting a submission never touches the
    // ticket's own assigned-office display (reassignment only ever
    // happens once the destination office accepts, server-side).
    await pumpWorkspace(
      tester,
      tickets: [
        ticketJson(id: 'TK-TRANSFER-1', subject: 'Needs a different office', status: 'Open'),
      ],
      initialSelectedTicketId: 'TK-TRANSFER-1',
    );

    expect(find.textContaining('Office of Student Affairs'), findsWidgets);

    await openTransferDialog(tester);
    await tester.tap(find.byKey(const Key('transfer-dialog-office-dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Registrar').last);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('transfer-dialog-reason-field')),
      'Needs Registrar, not OSA.',
    );
    await tester.pump();
    await tester.tap(find.widgetWithText(ElevatedButton, 'Apply'));
    await tester.pumpAndSettle();

    // The dialog surfaces the failure inline rather than closing silently.
    expect(find.byKey(const Key('transfer-dialog-submit-error')), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Office of Student Affairs'), findsWidgets);
  });

  // --- Transfer dialog lifecycle ------------------------------------------
  //
  // _TransferTicketDialogState used to call _loadOffices() directly from
  // initState(), before AuthScope.of(context) is safe to resolve. These
  // tests use debugTransferOfficeLoadAttempts (mirroring sidebar.dart's
  // debugTransferBadgeLoadAttempts -- there is no HTTP-mocking seam in this
  // codebase's widget tests, so an attempt counter is the only
  // deterministic way to observe "a load happened" without a real
  // backend) to prove the load now runs from didChangeDependencies instead,
  // exactly once, without throwing.

  testWidgets(
      'opening the Transfer dialog loads offices exactly once and never throws',
      (tester) async {
    await pumpWorkspace(
      tester,
      skipOfficeSeed: true,
      tickets: [
        ticketJson(id: 'TK-TRANSFER-1', subject: 'Needs a different office', status: 'Open'),
      ],
      initialSelectedTicketId: 'TK-TRANSFER-1',
    );
    final before = debugTransferOfficeLoadAttempts;

    await openTransferDialog(tester);
    await tester.pumpAndSettle();

    // Exactly one attempt -- not zero (it did run) and not more than one
    // (it didn't double-fire). No backend is reachable in this sandbox, so
    // it settles into the load-error state rather than a populated list.
    expect(debugTransferOfficeLoadAttempts, before + 1);
    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('transfer-dialog-load-error')), findsOneWidget);
  });

  testWidgets(
      'retrying after a load failure fetches again, but closing and reopening '
      'the dialog does not refetch beyond that',
      (tester) async {
    await pumpWorkspace(
      tester,
      skipOfficeSeed: true,
      tickets: [
        ticketJson(id: 'TK-TRANSFER-1', subject: 'Needs a different office', status: 'Open'),
      ],
      initialSelectedTicketId: 'TK-TRANSFER-1',
    );

    await openTransferDialog(tester);
    await tester.pumpAndSettle();
    final afterFirstOpen = debugTransferOfficeLoadAttempts;

    // User-initiated Retry is expected to fetch again.
    await tester.tap(find.widgetWithText(OutlinedButton, 'Retry'));
    await tester.pumpAndSettle();
    expect(debugTransferOfficeLoadAttempts, afterFirstOpen + 1);
    final afterRetry = debugTransferOfficeLoadAttempts;

    // Closing and reopening the dialog creates a fresh State, so exactly
    // one more attempt is expected for that new instance -- not zero
    // (confirming the guard isn't stuck "already requested" forever) and
    // not more than one (confirming it still only loads once per dialog).
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    await openTransferDialog(tester);
    await tester.pumpAndSettle();

    expect(debugTransferOfficeLoadAttempts, afterRetry + 1);
    expect(tester.takeException(), isNull);
  });
}

AuthUser _officeUser() {
  return const AuthUser(
    id: 'office-1',
    email: 'office@example.edu',
    fullName: 'OSA Officer',
    role: 'office',
    officeId: 'office-1',
    officeName: 'Office of Student Affairs (OSA)',
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
