import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_management_pages.dart';
import 'package:aska_piyu/services/auth_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final now = DateTime(2026, 9, 16, 12, 0);

  Map<String, dynamic> ticketJson({
    required String id,
    required String subject,
    required String status,
    required String office,
    required String createdAt,
    String priority = 'Medium',
  }) {
    return {
      'ticket_id': id,
      'id': id,
      'user_id': 'user-1',
      'user_name': 'Ana Santos',
      'user_email': 'ana.santos@example.edu',
      'original_question': subject,
      'description': subject,
      'status': status,
      'priority': priority,
      'category': 'Student Records',
      'assigned_office': office,
      'assigned_office_name': office,
      'created_at': createdAt,
      'updated_at': createdAt,
      'messages': const <Map<String, dynamic>>[],
    };
  }

  List<Map<String, dynamic>> sampleTickets() {
    return [
      ticketJson(
        id: 'TK-20260916-008',
        subject: 'Need steps and fee for issuance of Good Moral Certificate',
        status: 'Open',
        office: 'Office of Student Affairs (OSA)',
        createdAt: '2026-09-16T10:00:00',
        priority: 'High',
      ),
      ticketJson(
        id: 'TK-20260916-007',
        subject: 'How do I get an excuse slip if I missed class?',
        status: 'Open',
        office: 'Office of Student Affairs (OSA)',
        createdAt: '2026-09-16T07:00:00',
      ),
      ticketJson(
        id: 'TK-20260916-006',
        subject: 'Reset my student portal password',
        status: 'In Progress',
        office: 'Information and Communications Technology Unit',
        createdAt: '2026-09-16T04:00:00',
      ),
      ticketJson(
        id: 'TK-20260915-005',
        subject: 'Enrollment requirements for transferees',
        status: 'Closed',
        office: 'Admissions Office',
        createdAt: '2026-09-15T12:00:00',
      ),
      ticketJson(
        id: 'TK-20260915-004',
        subject: 'Counseling appointment follow-up',
        status: 'Resolved',
        office: 'Office of Student Affairs (OSA)',
        createdAt: '2026-09-15T11:00:00',
        priority: 'Low',
      ),
      ticketJson(
        id: 'TK-20260914-003',
        subject: 'Request for certificate of registration',
        status: 'Closed',
        office: 'Office of the Registrar',
        createdAt: '2026-09-14T12:00:00',
      ),
      ticketJson(
        id: 'TK-20260913-002',
        subject: 'Where do I claim my TOR?',
        status: 'Open',
        office: 'Office of the Registrar',
        createdAt: '2026-09-13T12:00:00',
      ),
      ticketJson(
        id: 'TK-20260910-001',
        subject: 'Scholarship clearance',
        status: 'Closed',
        office: 'Office of Student Affairs (OSA)',
        createdAt: '2026-09-10T12:00:00',
      ),
    ];
  }

  Future<void> pumpPage(
    WidgetTester tester, {
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? tickets,
    String? error,
    DateTime? clock,
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(service: _FakeAuthService(_adminUser()));
    await controller.login(
      const LoginRequest(email: 'admin@example.edu', password: 'password'),
    );

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: AdminDashboardPage(
            debugTickets: tickets ?? sampleTickets(),
            debugError: error,
            debugNow: clock ?? now,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('Dashboard loads real ticket data and four summary cards', (
    tester,
  ) async {
    await pumpPage(tester);

    expect(find.byKey(const Key('admin-dashboard-page')), findsOneWidget);
    expect(find.text('Admin Dashboard'), findsWidgets);
    expect(
      find.text('Monitor support activity and administrative workload.'),
      findsOneWidget,
    );
    expect(find.text('Total Tickets'), findsOneWidget);
    expect(find.text('Open Tickets'), findsOneWidget);
    expect(find.text('In Progress'), findsWidgets);
    expect(find.text('Closed'), findsWidgets);
    expect(find.text('Recent Tickets'), findsOneWidget);
    expect(
      find.text('Latest support tickets across all offices.'),
      findsOneWidget,
    );
  });

  testWidgets('summary counts use All Tickets semantics', (tester) async {
    await pumpPage(tester);

    expect(
      find.descendant(
        of: find.byKey(const Key('admin-dashboard-stat-total')),
        matching: find.text('8'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-dashboard-stat-open')),
        matching: find.text('3'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-dashboard-stat-progress')),
        matching: find.text('1'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-dashboard-stat-closed')),
        matching: find.text('3'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('Resolved is not counted as Closed', (tester) async {
    await pumpPage(tester);

    expect(
      find.descendant(
        of: find.byKey(const Key('admin-dashboard-stat-closed')),
        matching: find.text('4'),
      ),
      findsNothing,
    );
    expect(find.text('Resolved'), findsOneWidget);
  });

  testWidgets('Recent Tickets shows latest five newest first', (tester) async {
    await pumpPage(tester);

    expect(find.byKey(const Key('admin-dashboard-row-TK-20260916-008')), findsOneWidget);
    expect(find.byKey(const Key('admin-dashboard-row-TK-20260916-007')), findsOneWidget);
    expect(find.byKey(const Key('admin-dashboard-row-TK-20260916-006')), findsOneWidget);
    expect(find.byKey(const Key('admin-dashboard-row-TK-20260915-005')), findsOneWidget);
    expect(find.byKey(const Key('admin-dashboard-row-TK-20260915-004')), findsOneWidget);
    expect(find.byKey(const Key('admin-dashboard-row-TK-20260914-003')), findsNothing);
    expect(find.byKey(const Key('admin-dashboard-row-TK-20260910-001')), findsNothing);

    final first = tester.getTopLeft(
      find.byKey(const Key('admin-dashboard-row-TK-20260916-008')),
    );
    final second = tester.getTopLeft(
      find.byKey(const Key('admin-dashboard-row-TK-20260916-007')),
    );
    expect(first.dy < second.dy, isTrue);
  });

  testWidgets('ticket IDs, offices, and status (not priority) render', (
    tester,
  ) async {
    await pumpPage(tester);

    expect(find.text('TK-20260916-008'), findsOneWidget);
    expect(find.text('Office of Student Affairs (OSA)'), findsWidgets);
    expect(find.text('Information and Communications Technology Unit'), findsOneWidget);
    expect(find.text('Admissions Office'), findsOneWidget);
    expect(find.text('Open'), findsWidgets);
    expect(find.text('In Progress'), findsWidgets);
    expect(find.text('Closed'), findsWidgets);
    expect(find.text('High Priority'), findsNothing);
    expect(find.text('High'), findsNothing);
    expect(find.text('2 hours ago'), findsOneWidget);
    expect(find.text('5 hours ago'), findsOneWidget);
    expect(find.text('1 day ago'), findsWidgets);
  });

  testWidgets('View all opens Admin All Tickets', (tester) async {
    await pumpPage(tester);
    await tester.tap(find.byKey(const Key('admin-dashboard-view-all')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('All Tickets'), findsWidgets);
    expect(
      find.text(
        'Review and manage all student support tickets across offices and statuses.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('Open card navigates to All Tickets with Open filter', (
    tester,
  ) async {
    await pumpPage(tester);
    await tester.tap(find.byKey(const Key('admin-dashboard-stat-open')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('All Tickets'), findsWidgets);
    final status = tester.widget<FormField<String>>(
      find.byKey(const Key('admin-all-tickets-status-filter')),
    );
    expect(status.initialValue, 'Open');
  });

  testWidgets('empty state is explained without icons', (tester) async {
    await pumpPage(tester, tickets: const []);
    expect(find.text('No tickets yet.'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-dashboard-empty')),
        matching: find.byType(Icon),
      ),
      findsNothing,
    );
  });

  testWidgets('error and retry state is explained', (tester) async {
    await pumpPage(
      tester,
      tickets: const [],
      error: 'Could not load tickets.',
    );
    expect(find.byKey(const Key('admin-dashboard-error')), findsOneWidget);
    expect(find.text('Could not load tickets.'), findsOneWidget);
    expect(find.text('Retry'), findsOneWidget);
    await tester.tap(find.byKey(const Key('admin-dashboard-retry')));
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('narrow layout has no overflow or table header', (tester) async {
    await pumpPage(tester, size: const Size(400, 900));

    expect(tester.takeException(), isNull);
    expect(find.text('TICKET ID'), findsNothing);
    await tester.scrollUntilVisible(
      find.byKey(const Key('admin-dashboard-row-TK-20260916-008')),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('TK-20260916-008'), findsOneWidget);
    expect(find.byKey(const Key('admin-dashboard-clock')), findsNothing);
  });

  testWidgets('dashboard content has no icons, arrows, or chevrons', (
    tester,
  ) async {
    await pumpPage(tester);

    expect(
      find.descendant(
        of: find.byKey(const Key('admin-dashboard-page')),
        matching: find.byType(Icon),
      ),
      findsNothing,
    );
    expect(find.text('View all'), findsOneWidget);
    expect(find.text('View all →'), findsNothing);
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);
    expect(find.byIcon(Icons.arrow_forward_rounded), findsNothing);
    expect(find.byIcon(Icons.calendar_today_rounded), findsNothing);
    expect(find.byIcon(Icons.access_time_rounded), findsNothing);
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-dashboard-clock')),
        matching: find.byType(Icon),
      ),
      findsNothing,
    );
    expect(find.text('Sep 16, 2026'), findsOneWidget);
    expect(find.text('Wednesday, 12:00 PM'), findsOneWidget);
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
    _token = 'token';
    return AuthResponse(
      accessToken: 'token',
      tokenType: 'bearer',
      user: user,
    );
  }

  @override
  Future<AuthUser> getCurrentUser(String token) async => user;
}
