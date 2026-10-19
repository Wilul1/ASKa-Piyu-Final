import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/my_tickets_page.dart';
import 'package:aska_piyu/services/auth_service.dart';

/// Covers the My Tickets redesign toward a clean, compact, HESK-style
/// list: ID-only ticket cards (the ticket ID is the card's primary
/// text -- no subject, priority chip, office/category/reply-count
/// line, or description preview -- just ID, status, and last-updated
/// date), a clear "Submit a Ticket" action on the genuinely-empty
/// state, a burgundy Submit Ticket button on the compact heading at
/// every width, the status summary being phone-only-hidden, and
/// Resolved tickets being excluded from the default dashboard list
/// while still reachable through the existing status filter.
/// TicketCard and TicketEmptyState are plain, data-in widgets, so those
/// are pumped directly rather than through MyTicketsPage -- there is no
/// HTTP-mocking seam in this codebase's widget tests to seed a
/// populated ticket list through the real page; the dashboard-filtering
/// behavior below is instead covered as a pure unit test against
/// [visibleTicketsForDashboard] itself.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  TicketEntry buildTicket({
    String id = 'TK-20261019-ABC123',
    String subject = 'Request for transcript of records',
    String status = 'Open',
    String priority = 'High',
    String category = 'Registrar',
    String assignedOffice = 'Registrar Office',
    String description = 'I need my transcript for a job application.',
    int replyCount = 2,
  }) {
    return TicketEntry(
      id: id,
      userId: 'student-1',
      userName: 'Juan Dela Cruz',
      userEmail: 'student@example.edu',
      subject: subject,
      status: status,
      createdAt: DateTime(2026, 10, 1, 9, 0),
      updatedAt: DateTime(2026, 10, 19, 14, 30),
      resolvedAt: null,
      closedAt: null,
      category: category,
      assignedOffice: assignedOffice,
      priority: priority,
      description: description,
      confidenceScore: null,
      sourceFromChatbot: false,
      messages: [
        for (var i = 0; i < replyCount; i++)
          TicketMessage(
            id: 'msg-$i',
            ticketId: id,
            senderId: 'office-1',
            senderRole: 'office',
            senderName: 'Registrar Staff',
            message: 'Reply $i',
            createdAt: DateTime(2026, 10, 19, 10 + i),
          ),
      ],
    );
  }

  Future<void> pumpCard(WidgetTester tester, TicketEntry ticket) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: TicketCard(ticket: ticket, onTap: () {})),
      ),
    );
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

  Future<void> pumpListTab(WidgetTester tester, {required Size size}) async {
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
        child: const MaterialApp(home: MyTicketsPage()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  // --- ID-only compact card -----------------------------------------------

  testWidgets(
      'the ticket card shows the ticket ID as its primary text, plus '
      'status and the last-updated date', (tester) async {
    await pumpCard(tester, buildTicket());

    expect(find.text('TK-20261019-ABC123'), findsOneWidget);
    expect(find.text('Open'), findsOneWidget);
    expect(find.textContaining('Oct 19'), findsOneWidget);
  });

  testWidgets(
      'the ticket card does not show the subject, priority, office/'
      'category, reply count, or a description preview -- ID-only, '
      'trimmed for a clean, non-noisy list', (tester) async {
    await pumpCard(tester, buildTicket());

    expect(find.text('Request for transcript of records'), findsNothing);
    expect(find.text('High'), findsNothing);
    expect(find.text('Registrar Office'), findsNothing);
    expect(find.text('Registrar'), findsNothing);
    expect(find.textContaining('replies'), findsNothing);
    expect(find.textContaining('reply'), findsNothing);
    expect(
      find.text('I need my transcript for a job application.'),
      findsNothing,
    );
  });

  test(
      'the subject survives on the TicketEntry model itself -- removing '
      'it from the dashboard card never touched the ticket data, which '
      'TicketDetailsPage (opened on tap) still reads', () {
    final ticket = buildTicket();

    expect(ticket.subject, 'Request for transcript of records');
  });

  testWidgets('the ticket card has no overflow at a narrow phone width, '
      'even with a long ticket ID', (tester) async {
    tester.view.physicalSize = const Size(360, 700);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final unexpectedErrors = <String>[];
    final previousOnError = FlutterError.onError;
    FlutterError.onError = (details) {
      unexpectedErrors.add(details.toString());
      previousOnError?.call(details);
    };
    addTearDown(() => FlutterError.onError = previousOnError);

    await pumpCard(
      tester,
      buildTicket(id: 'TK-20261019-A-MUCH-LONGER-TICKET-ID-THAN-USUAL-001'),
    );

    expect(unexpectedErrors, isEmpty);
  });

  testWidgets('tapping the card invokes onTap', (tester) async {
    var tapped = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TicketCard(
            ticket: buildTicket(),
            onTap: () => tapped = true,
          ),
        ),
      ),
    );

    await tester.tap(find.text('TK-20261019-ABC123'));
    await tester.pump();

    expect(tapped, isTrue);
  });

  // --- Empty state: clear "Submit a Ticket" action on true empty ----------

  testWidgets(
      'the genuinely-empty state ("No tickets yet") shows a "Submit a '
      'Ticket" action', (tester) async {
    var tapped = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TicketEmptyState(
            title: 'No tickets yet',
            message: 'Submitted support requests will appear here.',
            onSubmitTicket: () => tapped = true,
          ),
        ),
      ),
    );

    expect(find.text('No tickets yet'), findsOneWidget);
    final button = find.widgetWithText(ElevatedButton, 'Submit a Ticket');
    expect(button, findsOneWidget);

    await tester.tap(button);
    await tester.pump();
    expect(tapped, isTrue);
  });

  testWidgets(
      'the filtered-empty state ("No matching tickets") shows no Submit '
      'a Ticket action -- the student already has tickets', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TicketEmptyState(
            title: 'No matching tickets',
            message: 'Try changing the search text, status, or filter.',
          ),
        ),
      ),
    );

    expect(find.text('No matching tickets'), findsOneWidget);
    expect(find.widgetWithText(ElevatedButton, 'Submit a Ticket'), findsNothing);
  });

  // --- Compact heading's Submit Ticket button ------------------------------

  testWidgets(
      'the compact heading shows a Submit Ticket button at a phone '
      'width', (tester) async {
    await pumpListTab(tester, size: const Size(390, 844));

    expect(
      find.widgetWithText(ElevatedButton, 'Submit Ticket'),
      findsOneWidget,
    );
  });

  testWidgets(
      'tapping the heading\'s Submit Ticket button switches to the '
      'existing Submit Ticket tab -- no separate/duplicate submission '
      'flow', (tester) async {
    await pumpListTab(tester, size: const Size(390, 844));

    // Starts on the List tab -- the Submit Ticket form isn't showing yet.
    expect(find.text('Submit a Support Request'), findsNothing);

    await tester.tap(find.widgetWithText(ElevatedButton, 'Submit Ticket'));
    await tester.pumpAndSettle();

    // The same Submit Ticket tab/form this page has always had.
    expect(find.text('Submit a Support Request'), findsOneWidget);
  });

  testWidgets(
      'the heading and its Submit Ticket button have no horizontal '
      'overflow at a narrow phone width (360px)', (tester) async {
    final unexpectedErrors = <String>[];
    final previousOnError = FlutterError.onError;
    FlutterError.onError = (details) {
      unexpectedErrors.add(details.toString());
      previousOnError?.call(details);
    };
    addTearDown(() => FlutterError.onError = previousOnError);

    await pumpListTab(tester, size: const Size(360, 800));

    expect(unexpectedErrors, isEmpty);
    expect(find.text('My Tickets'), findsOneWidget);
    expect(
      find.widgetWithText(ElevatedButton, 'Submit Ticket'),
      findsOneWidget,
    );
  });

  testWidgets(
      'the Submit Ticket button is also present and tappable on desktop '
      '(1200px), alongside the heading', (tester) async {
    await pumpListTab(tester, size: const Size(1200, 900));

    // At this wide width the header's own "My Tickets" nav link
    // (now active) legitimately matches too, alongside the heading.
    expect(find.text('My Tickets'), findsWidgets);
    expect(
      find.widgetWithText(ElevatedButton, 'Submit Ticket'),
      findsOneWidget,
    );
  });

  // --- Status summary: phone-hidden, tablet/desktop-visible ---------------
  //
  // _TicketStatsSummary always renders regardless of ticket count (it
  // shows zeroes with no tickets loaded), so its own "Open"/"In
  // Progress"/"Closed"/"Total" labels are enough to detect its presence
  // without needing a populated list.

  testWidgets('the status summary is hidden on a phone width (360px)',
      (tester) async {
    await pumpListTab(tester, size: const Size(360, 800));

    expect(find.text('Open'), findsNothing);
    expect(find.text('In Progress'), findsNothing);
    expect(find.text('Closed'), findsNothing);
    expect(find.text('Total'), findsNothing);
  });

  testWidgets(
      'the status summary is hidden right up to the phone breakpoint '
      '(879px)', (tester) async {
    await pumpListTab(tester, size: const Size(879, 800));

    expect(find.text('Open'), findsNothing);
  });

  testWidgets(
      'the status summary is visible at the phone breakpoint and above '
      '(880px, tablet)', (tester) async {
    await pumpListTab(tester, size: const Size(880, 900));

    expect(find.text('Open'), findsOneWidget);
    expect(find.text('In Progress'), findsOneWidget);
    expect(find.text('Closed'), findsOneWidget);
    expect(find.text('Total'), findsOneWidget);
  });

  testWidgets('the status summary is visible on desktop (1200px)',
      (tester) async {
    await pumpListTab(tester, size: const Size(1200, 900));

    expect(find.text('Open'), findsOneWidget);
    expect(find.text('Total'), findsOneWidget);
  });

  testWidgets(
      'hiding the status summary on a phone leaves no blank gap -- the '
      'toolbar sits directly below the heading block, not hundreds of '
      'extra pixels down where a ~150px+ stats panel would otherwise '
      'have pushed it', (tester) async {
    await pumpListTab(tester, size: const Size(360, 800));

    // The search field is the toolbar's first control. The heading
    // block itself is now taller than before this change (it carries
    // its own Submit Ticket button, stacked below the title on a
    // phone), so the bound here is generous enough for that legitimate
    // height while still well short of what an extra stats panel
    // (another ~150px+) would have added on top of it.
    final searchFieldTop = tester.getTopLeft(find.byType(TextField).first).dy;
    expect(searchFieldTop, lessThan(280));
  });

  // --- Default dashboard filtering: Resolved hidden, Closed stays -------

  group('visibleTicketsForDashboard', () {
    TicketEntry ticket(String id, String status) {
      return TicketEntry(
        id: id,
        userId: 'student-1',
        userName: 'Juan Dela Cruz',
        userEmail: 'student@example.edu',
        subject: 'Subject for $id',
        status: status,
        createdAt: DateTime(2026, 10, 1),
        updatedAt: DateTime(2026, 10, 1),
        resolvedAt: null,
        closedAt: null,
        category: 'General',
        assignedOffice: 'Registrar Office',
        priority: 'Low',
        description: '',
        confidenceScore: null,
        sourceFromChatbot: false,
        messages: const [],
      );
    }

    final tickets = [
      ticket('TK-OPEN', 'Open'),
      ticket('TK-PROGRESS', 'In Progress'),
      ticket('TK-RESOLVED', 'Resolved'),
      ticket('TK-CLOSED', 'Closed'),
    ];

    test('the default ("All Status") view excludes Resolved but keeps '
        'Open, In Progress, and Closed', () {
      final visible = visibleTicketsForDashboard(
        tickets,
        '',
        'All',
        officeFilter: 'All Offices',
        categoryFilter: 'All Categories',
      );

      expect(visible.map((t) => t.id), containsAll(['TK-OPEN', 'TK-PROGRESS', 'TK-CLOSED']));
      expect(visible.map((t) => t.id), isNot(contains('TK-RESOLVED')));
    });

    test('explicitly selecting the Resolved status filter reveals it', () {
      final visible = visibleTicketsForDashboard(
        tickets,
        '',
        'Resolved',
        officeFilter: 'All Offices',
        categoryFilter: 'All Categories',
      );

      expect(visible.map((t) => t.id), ['TK-RESOLVED']);
    });

    test('explicitly selecting the Closed status filter still works '
        'normally (unaffected by the Resolved-hiding default)', () {
      final visible = visibleTicketsForDashboard(
        tickets,
        '',
        'Closed',
        officeFilter: 'All Offices',
        categoryFilter: 'All Categories',
      );

      expect(visible.map((t) => t.id), ['TK-CLOSED']);
    });

    test('selecting the Open status filter is unaffected by the '
        'Resolved-hiding default', () {
      final visible = visibleTicketsForDashboard(
        tickets,
        '',
        'Open',
        officeFilter: 'All Offices',
        categoryFilter: 'All Categories',
      );

      expect(visible.map((t) => t.id), ['TK-OPEN']);
    });
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
