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
    required String office,
    // Real office id the raw `office` label resolved to. Defaults to null
    // (unresolved / needs manual routing) unless the caller passes one --
    // see sampleTickets(), which sets this for every ticket whose office
    // is one of sampleOffices() so the existing fixtures stay "resolved".
    String? officeId,
    String priority = 'Medium',
    String requester = 'Ana Santos',
    String email = 'ana.santos@example.edu',
    String createdAt = '2026-09-13T02:24:00Z',
  }) {
    return {
      'ticket_id': id,
      'id': id,
      'user_id': 'user-1',
      'user_name': requester,
      'user_email': email,
      'original_question': subject,
      'description': subject,
      'status': status,
      'priority': priority,
      'category': 'Student Records',
      'assigned_office': office,
      'assigned_office_name': office,
      'assigned_office_id': officeId,
      'created_at': createdAt,
      'updated_at': createdAt,
      'messages': const <Map<String, dynamic>>[],
    };
  }

  List<Map<String, dynamic>> sampleTickets() {
    return [
      ticketJson(
        id: 'TK-20260913-001',
        subject: 'Need steps and fee for issuance of Good Moral Certificate',
        status: 'Open',
        office: 'Office of Student Affairs (OSA)',
        officeId: 'o3',
        createdAt: '2026-09-13T02:24:00Z',
        requester: 'Wilmark Veridiano',
        email: 'wilmarkveridiano9@gmail.com',
      ),
      ticketJson(
        id: 'TK-20260913-002',
        subject: 'How do I get an excuse slip if I missed class?',
        status: 'Open',
        office: 'Office of Student Affairs (OSA)',
        officeId: 'o3',
        priority: 'High',
        createdAt: '2026-09-13T01:18:00Z',
        requester: 'Test User',
        email: 'test@gmail.com',
      ),
      ticketJson(
        id: 'TK-20260912-028',
        subject: 'Enrollment requirements for transferees',
        status: 'Closed',
        office: 'Admissions Office',
        officeId: 'o1',
        priority: 'Low',
        createdAt: '2026-09-12T08:32:00Z',
        requester: 'Juan Dela Cruz',
        email: 'juan.dela.cruz@ls.example.edu',
      ),
      ticketJson(
        id: 'TK-20260912-027',
        subject: 'Request for certificate of registration',
        status: 'Closed',
        office: 'Office of the Registrar',
        officeId: 'o4',
        createdAt: '2026-09-12T06:11:00Z',
        requester: 'Maria Santos',
        email: 'maria.santos@ls.example.edu',
      ),
      ticketJson(
        id: 'TK-20260912-026',
        subject: 'Reset my student portal password',
        status: 'In Progress',
        office: 'Information and Communications Technology Unit',
        officeId: 'o2',
        createdAt: '2026-09-12T03:03:00Z',
        requester: 'Carlo Reyes',
        email: 'carlo.reyes@ls.example.edu',
      ),
      ticketJson(
        id: 'TK-20260911-010',
        subject: 'Counseling appointment follow-up',
        status: 'Resolved',
        office: 'Office of Student Affairs (OSA)',
        officeId: 'o3',
        priority: 'Low',
        createdAt: '2026-09-11T08:00:00Z',
      ),
      ticketJson(
        id: 'TK-20260910-005',
        subject: 'Where do I claim my TOR?',
        status: 'Open',
        office: 'Office of the Registrar',
        officeId: 'o4',
        priority: 'Urgent',
        createdAt: '2026-09-10T09:00:00Z',
      ),
      ticketJson(
        id: 'TK-20260909-004',
        subject: 'Scholarship clearance',
        status: 'Closed',
        office: 'Office of Student Affairs (OSA)',
        officeId: 'o3',
        createdAt: '2026-09-09T09:00:00Z',
      ),
      ticketJson(
        id: 'TK-20260908-003',
        subject: 'Late enrollment appeal',
        status: 'Closed',
        office: 'Admissions Office',
        officeId: 'o1',
        createdAt: '2026-09-08T09:00:00Z',
      ),
      ticketJson(
        id: 'TK-20260907-002',
        subject: 'ID reprint request',
        status: 'Closed',
        office: 'Office of the Registrar',
        officeId: 'o4',
        createdAt: '2026-09-07T09:00:00Z',
      ),
      ticketJson(
        id: 'TK-20260906-001',
        subject: 'Wifi access in the library',
        status: 'Closed',
        office: 'Information and Communications Technology Unit',
        officeId: 'o2',
        createdAt: '2026-09-06T09:00:00Z',
      ),
    ];
  }

  // A 12th, unresolved-specific-office ticket: no seeded office matches its
  // raw taxonomy label, so assigned_office_id stays null. Used by the
  // dedicated "needs manual routing" tests below; kept out of
  // sampleTickets() so the existing 11-ticket-count assertions elsewhere
  // in this file are untouched.
  Map<String, dynamic> unresolvedTicketJson() {
    return ticketJson(
      id: 'TK-20260914-001',
      subject: 'Enrollment requirements for the College of Agriculture',
      status: 'Open',
      office: 'College of Agriculture',
      officeId: null,
      createdAt: '2026-09-14T09:00:00Z',
      requester: 'Nora Ibarra',
      email: 'nora.ibarra@ls.example.edu',
    );
  }

  List<Map<String, dynamic>> sampleOffices() {
    return [
      {'id': 'o1', 'name': 'Admissions Office'},
      {'id': 'o2', 'name': 'Information and Communications Technology Unit'},
      {'id': 'o3', 'name': 'Office of Student Affairs (OSA)'},
      {'id': 'o4', 'name': 'Office of the Registrar'},
    ];
  }

  Future<void> pumpPage(
    WidgetTester tester, {
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? tickets,
    List<Map<String, dynamic>>? offices,
    String? error,
    String initialStatusFilter = 'All',
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(service: _FakeAuthService(_adminUser()));
    await controller.login(const LoginRequest(
      email: 'admin@example.edu',
      password: 'password',
    ));

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: AdminAllTicketsPage(
            initialStatusFilter: initialStatusFilter,
            debugTickets: tickets ?? sampleTickets(),
            debugOffices: offices ?? sampleOffices(),
            debugError: error,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  Future<void> chooseDropdown(
    WidgetTester tester, {
    required Key key,
    required String option,
  }) async {
    await tester.tap(find.byKey(key));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.tap(find.text(option).last);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
  }

  testWidgets('All Tickets loads the compact management table', (tester) async {
    await pumpPage(tester);

    expect(find.byKey(const Key('admin-all-tickets-page')), findsOneWidget);
    expect(find.text('All Tickets'), findsWidgets);
    expect(
      find.text(
        'Review and manage all student support tickets across offices and statuses.',
      ),
      findsOneWidget,
    );
    expect(find.text('TICKET ID'), findsOneWidget);
    expect(find.text('SUBJECT'), findsOneWidget);
    expect(find.text('OFFICE'), findsOneWidget);
    expect(find.text('REQUESTER'), findsOneWidget);
    expect(find.text('STATUS'), findsOneWidget);
    expect(find.text('PRIORITY'), findsOneWidget);
    expect(find.text('CREATED AT'), findsOneWidget);
    expect(find.text('ACTIONS'), findsOneWidget);
    expect(find.text('TK-20260913-001'), findsOneWidget);
  });

  testWidgets('summary cards use live ticket counts and keep Closed distinct',
      (tester) async {
    await pumpPage(tester);

    expect(
      find.descendant(
        of: find.byKey(const Key('admin-all-tickets-stat-total')),
        matching: find.text('11'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-all-tickets-stat-open')),
        matching: find.text('3'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-all-tickets-stat-progress')),
        matching: find.text('1'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-all-tickets-stat-closed')),
        matching: find.text('6'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('search by ticket ID', (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.byKey(const Key('admin-all-tickets-search')),
      'TK-20260913-002',
    );
    await tester.pump();

    expect(find.byKey(const Key('admin-all-tickets-row-TK-20260913-002')), findsOneWidget);
    expect(find.byKey(const Key('admin-all-tickets-row-TK-20260913-001')), findsNothing);
    expect(find.text('Showing 1–1 of 1 tickets'), findsOneWidget);
  });

  testWidgets('search by subject', (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.byKey(const Key('admin-all-tickets-search')),
      'excuse slip',
    );
    await tester.pump();

    expect(find.text('TK-20260913-002'), findsOneWidget);
    expect(find.text('TK-20260913-001'), findsNothing);
  });

  testWidgets('search by requester email', (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.byKey(const Key('admin-all-tickets-search')),
      'wilmarkveridiano9@gmail.com',
    );
    await tester.pump();

    expect(find.text('TK-20260913-001'), findsOneWidget);
    expect(find.text('TK-20260913-002'), findsNothing);
  });

  testWidgets('office, status, and priority filters compose', (tester) async {
    await pumpPage(tester);

    await chooseDropdown(
      tester,
      key: const Key('admin-all-tickets-office-filter'),
      option: 'Office of Student Affairs (OSA)',
    );
    expect(find.text('TK-20260913-001'), findsOneWidget);
    expect(find.text('TK-20260912-027'), findsNothing);

    await chooseDropdown(
      tester,
      key: const Key('admin-all-tickets-status-filter'),
      option: 'Open',
    );
    expect(find.text('TK-20260913-001'), findsOneWidget);
    expect(find.text('TK-20260913-002'), findsOneWidget);
    expect(find.text('TK-20260909-004'), findsNothing);

    await chooseDropdown(
      tester,
      key: const Key('admin-all-tickets-priority-filter'),
      option: 'High',
    );
    expect(find.text('TK-20260913-002'), findsOneWidget);
    expect(find.text('TK-20260913-001'), findsNothing);
    expect(find.text('Showing 1–1 of 1 tickets'), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('admin-all-tickets-search')),
      'excuse',
    );
    await tester.pump();
    expect(find.text('TK-20260913-002'), findsOneWidget);
  });

  testWidgets('Reset Filters clears office/status/priority but keeps search',
      (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.byKey(const Key('admin-all-tickets-search')),
      'excuse',
    );
    await tester.pump();
    await chooseDropdown(
      tester,
      key: const Key('admin-all-tickets-status-filter'),
      option: 'Closed',
    );
    expect(find.byKey(const Key('admin-all-tickets-empty')), findsOneWidget);

    await tester.tap(find.byKey(const Key('admin-all-tickets-reset')));
    await tester.pump();

    expect(find.text('TK-20260913-002'), findsOneWidget);
    expect(find.text('TK-20260913-001'), findsNothing);
    expect(
      find.byKey(const Key('admin-all-tickets-search')),
      findsOneWidget,
    );
  });

  testWidgets('pagination and search/filter reset to page 1', (tester) async {
    await pumpPage(tester);

    expect(find.text('Showing 1–5 of 11 tickets'), findsOneWidget);
    expect(find.text('TK-20260913-001'), findsOneWidget);
    expect(find.text('TK-20260911-010'), findsNothing);

    await tester.tap(find.text('Next'));
    await tester.pump();
    expect(find.text('Showing 6–10 of 11 tickets'), findsOneWidget);
    expect(find.text('TK-20260911-010'), findsOneWidget);
    expect(find.text('TK-20260913-001'), findsNothing);

    await tester.enterText(
      find.byKey(const Key('admin-all-tickets-search')),
      'TK-20260913',
    );
    await tester.pump();
    expect(find.text('Showing 1–2 of 2 tickets'), findsOneWidget);
    expect(find.text('TK-20260913-001'), findsOneWidget);

    await tester.tap(find.byKey(const Key('admin-all-tickets-search')));
    await tester.enterText(
      find.byKey(const Key('admin-all-tickets-search')),
      '',
    );
    await tester.pump();
    await chooseDropdown(
      tester,
      key: const Key('admin-all-tickets-status-filter'),
      option: 'Closed',
    );
    expect(find.text('Showing 1–5 of 6 tickets'), findsOneWidget);
    expect(find.text('Next'), findsOneWidget);
  });

  testWidgets('View opens the existing admin ticket dialog', (tester) async {
    await pumpPage(tester);
    await tester.tap(find.byKey(const Key('admin-all-tickets-view-TK-20260913-001')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('Admin controls'), findsOneWidget);
    expect(find.text('TK-20260913-001'), findsWidgets);
    expect(
      find.text('Need steps and fee for issuance of Good Moral Certificate'),
      findsWidgets,
    );
  });

  testWidgets('status and priority badges and created timestamp render',
      (tester) async {
    await pumpPage(tester);

    expect(find.text('Open'), findsWidgets);
    expect(find.text('In Progress'), findsWidgets);
    expect(find.text('Closed'), findsWidgets);
    expect(find.text('High'), findsWidgets);
    expect(find.text('Medium'), findsWidgets);
    expect(find.text('Sep 13, 2026'), findsWidgets);
    expect(find.text('10:24 AM'), findsOneWidget);
  });

  testWidgets(
      'unresolved-office ticket shows a Needs Routing badge and can be filtered to',
      (tester) async {
    await pumpPage(
      tester,
      tickets: [...sampleTickets(), unresolvedTicketJson()],
    );

    // The badge renders once in the table row and again as the stat-row
    // toggle label, so just assert it shows up rather than pin a count.
    expect(find.text('Needs Routing'), findsWidgets);
    expect(find.byKey(const Key('admin-all-tickets-row-TK-20260914-001')),
        findsOneWidget);

    await tester.tap(
      find.byKey(const Key('admin-all-tickets-needs-routing-toggle')),
    );
    await tester.pump();

    expect(find.byKey(const Key('admin-all-tickets-row-TK-20260914-001')),
        findsOneWidget);
    expect(find.byKey(const Key('admin-all-tickets-row-TK-20260913-001')),
        findsNothing);
  });

  testWidgets(
      'unresolved-office ticket dialog explains the state and offers a real-office dropdown',
      (tester) async {
    await pumpPage(
      tester,
      tickets: [...sampleTickets(), unresolvedTicketJson()],
    );
    await tester.tap(
      find.byKey(const Key('admin-all-tickets-view-TK-20260914-001')),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('Needs Manual Routing'), findsWidgets);
    expect(
      find.textContaining('No office matches the taxonomy label'),
      findsOneWidget,
    );
    // The raw taxonomy label is still shown to admin (it isn't hidden --
    // just no longer treated as if it were a resolved assignment) ...
    expect(find.text('College of Agriculture'), findsWidgets);
    // ... while the reassignment control itself is the real-office-id
    // dropdown, not the old raw-name dropdown.
    expect(find.byKey(const Key('admin-ticket-office-id')), findsOneWidget);
  });

  testWidgets('empty search/filter state is explained', (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.byKey(const Key('admin-all-tickets-search')),
      'zzzz-no-match',
    );
    await tester.pump();

    expect(find.text('No matching tickets'), findsOneWidget);
    expect(find.byKey(const Key('admin-all-tickets-empty')), findsOneWidget);
    expect(find.byKey(const Key('admin-all-tickets-pager')), findsNothing);
  });

  testWidgets('API error state is displayed', (tester) async {
    await pumpPage(
      tester,
      tickets: const [],
      error: 'Could not load tickets.',
    );

    expect(find.byKey(const Key('admin-all-tickets-error')), findsOneWidget);
    expect(find.text('Could not load tickets.'), findsOneWidget);
  });

  testWidgets('narrow layout has no overflow', (tester) async {
    await pumpPage(tester, size: const Size(400, 900));

    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('admin-all-tickets-page')), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('admin-all-tickets-row-TK-20260913-001')),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('TK-20260913-001'), findsOneWidget);
    expect(find.text('TICKET ID'), findsNothing);
    expect(find.text('View'), findsWidgets);
  });

  testWidgets('Office Assigned Tickets is unaffected', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1400, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(service: _FakeAuthService(_officeUser()));
    await controller.login(const LoginRequest(
      email: 'office@example.edu',
      password: 'password',
    ));

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: OfficeAssignedTicketsPage(
            debugTickets: [
              ticketJson(
                id: 'TK-OPEN-1',
                subject: 'How do I request a Good Moral Certificate?',
                status: 'Open',
                office: 'Office of Student Affairs (OSA)',
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Assigned Tickets'), findsWidgets);
    expect(find.text('TK-OPEN-1'), findsOneWidget);
    expect(find.byType(Dialog), findsNothing);
    expect(find.text('Select a ticket to view the conversation.'), findsOneWidget);
    expect(find.text('Reset Filters'), findsNothing);
    expect(find.text('All Tickets'), findsNothing);
  });
}

AuthUser _adminUser() {
  return const AuthUser(
    id: 'admin-1',
    email: 'admin@example.edu',
    fullName: 'Campus Admin',
    role: 'admin',
    officeId: null,
    officeName: null,
    emailVerified: true,
    createdAt: null,
    updatedAt: null,
  );
}

AuthUser _officeUser() {
  return const AuthUser(
    id: 'office-1',
    email: 'office@example.edu',
    fullName: 'Office Staff',
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
