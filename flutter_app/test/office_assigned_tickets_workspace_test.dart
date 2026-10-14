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

  Future<void> pumpWorkspace(
    WidgetTester tester, {
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? tickets,
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
  // regression this guards, independent of the (legitimate, unrelated)
  // Priority dropdown and the status badge rendering twice (once in the
  // thread header, once in the always-visible details sidebar, at this
  // wide viewport).
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

  testWidgets('the Transfer dialog no longer offers a status dropdown',
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

    final transfer = find.byTooltip('Transfer / reassign', skipOffstage: false);
    await tester.ensureVisible(transfer);
    await tester.tap(transfer);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Transfer ticket'), findsOneWidget);
    // Office has allowReassignment: false, so with the status dropdown
    // removed this dialog now has no dropdowns of its own left at all --
    // scoped to inside the dialog, since the page behind it still has its
    // own (unrelated, legitimate) Priority dropdown.
    expect(
      find.descendant(
        of: find.byType(Dialog),
        matching: find.byType(DropdownButtonFormField<String>),
      ),
      findsNothing,
    );
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
