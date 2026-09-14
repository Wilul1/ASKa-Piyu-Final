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
    String priority = 'Medium',
    String requester = 'Ana Santos',
    String createdAt = '2026-09-13T02:24:00Z',
  }) {
    return {
      'ticket_id': id,
      'id': id,
      'user_id': 'user-1',
      'user_name': requester,
      'user_email': 'ana@example.edu',
      'original_question': subject,
      'description': subject,
      'status': status,
      'priority': priority,
      'category': 'Student Records',
      'assigned_office': 'College of Computer Studies (CCS)',
      'assigned_office_name': 'College of Computer Studies (CCS)',
      'created_at': createdAt,
      'updated_at': createdAt,
      'messages': const <Map<String, dynamic>>[],
    };
  }

  List<Map<String, dynamic>> sampleTickets() {
    return [
      ticketJson(
        id: 'TK-OPEN-1',
        subject: 'How do I request a Good Moral Certificate?',
        status: 'Open',
        requester: 'Wilmark Veridiano',
        createdAt: '2026-09-12T08:00:00Z',
      ),
      ticketJson(
        id: 'TK-PROG-1',
        subject: 'Excuse slip after two sick days',
        status: 'In Progress',
        priority: 'High',
        requester: 'Juan Dela Cruz',
        createdAt: '2026-09-11T08:00:00Z',
      ),
      ticketJson(
        id: 'TK-CLOSED-1',
        subject: 'Where do I claim my TOR?',
        status: 'Closed',
        requester: 'Maria Reyes',
        createdAt: '2026-09-10T08:00:00Z',
      ),
      ticketJson(
        id: 'TK-RES-1',
        subject: 'Enrollment assessment schedule',
        status: 'Resolved',
        priority: 'Urgent',
        requester: 'Pedro Gomez',
        createdAt: '2026-09-09T08:00:00Z',
      ),
    ];
  }

  Future<void> pumpDashboard(
    WidgetTester tester, {
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? tickets,
    String officeName = 'College of Computer Studies (CCS)',
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(
      service: _FakeAuthService(_officeUser(officeName: officeName)),
    );
    await controller.login(const LoginRequest(
      email: 'office@example.edu',
      password: 'password',
    ));

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: OfficeDashboardPage(
            debugTickets: tickets ?? sampleTickets(),
            debugNow: DateTime(2026, 9, 13, 10, 24),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('Office Dashboard renders', (tester) async {
    await pumpDashboard(tester);

    expect(find.text('WELCOME BACK'), findsOneWidget);
    expect(find.text('Office Dashboard'), findsWidgets);
    expect(find.text('Recent Tickets'), findsOneWidget);
    expect(find.text('View all tickets →'), findsOneWidget);
    expect(find.byType(Dialog), findsNothing);
  });

  testWidgets('authenticated office name appears dynamically', (tester) async {
    await pumpDashboard(
      tester,
      officeName: 'Office of Student Affairs (OSA)',
    );

    expect(
      find.text('Overview of workload for Office of Student Affairs (OSA).'),
      findsOneWidget,
    );
    expect(
      find.textContaining('College of Computer Studies (CCS)'),
      findsNothing,
    );
  });

  testWidgets('ticket statistic counts are calculated from real tickets',
      (tester) async {
    await pumpDashboard(tester);

    expect(find.text('Assigned Tickets'), findsWidgets);
    expect(find.text('Tickets assigned to your office'), findsOneWidget);
    expect(find.text('Open Tickets'), findsOneWidget);
    expect(find.text('Awaiting action'), findsOneWidget);
    expect(find.text('In Progress'), findsWidgets);
    expect(find.text('Currently being handled'), findsOneWidget);
    expect(find.text('Closed Tickets'), findsOneWidget);
    expect(find.text('Resolved tickets'), findsOneWidget);
    expect(find.text('High Priority'), findsOneWidget);
    expect(find.text('Requires immediate attention'), findsOneWidget);

    expect(find.text('4'), findsWidgets); // assigned
    expect(find.text('1'), findsWidgets); // open + in progress
    expect(find.text('2'), findsWidgets); // closed/resolved + high
  });

  testWidgets('Recent Tickets renders provided fixture data', (tester) async {
    await pumpDashboard(tester);

    expect(find.text('How do I request a Good Moral Certificate?'), findsOneWidget);
    expect(find.text('Excuse slip after two sick days'), findsOneWidget);
    expect(find.text('Wilmark Veridiano'), findsOneWidget);
    expect(find.text('Juan Dela Cruz'), findsOneWidget);
    expect(find.text('TITLE'), findsOneWidget);
    expect(find.text('REQUESTER'), findsOneWidget);
    expect(find.text('DATE ASSIGNED'), findsOneWidget);
  });

  testWidgets('empty state renders when there are no tickets', (tester) async {
    await pumpDashboard(tester, tickets: const []);

    expect(find.text('No recent tickets'), findsOneWidget);
    expect(
      find.text('Tickets assigned to your office will appear here.'),
      findsOneWidget,
    );
    expect(find.text('0'), findsWidgets);
    expect(find.text('How do I request a Good Moral Certificate?'), findsNothing);
  });

  testWidgets('View all tickets navigates to Assigned Tickets', (tester) async {
    await pumpDashboard(tester);

    await tester.tap(find.text('View all tickets →'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 80));

    expect(find.byType(OfficeAssignedTicketsPage), findsOneWidget);
    expect(find.byType(Dialog), findsNothing);
  });

  testWidgets('recent ticket opens Assigned Tickets inline without a popup',
      (tester) async {
    await pumpDashboard(tester);

    await tester.tap(find.text('How do I request a Good Moral Certificate?'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 80));

    expect(find.byType(OfficeAssignedTicketsPage), findsOneWidget);
    expect(find.byType(Dialog), findsNothing);
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('responsive layout does not overflow at a narrow width',
      (tester) async {
    await pumpDashboard(tester, size: const Size(400, 900));

    expect(tester.takeException(), isNull);
    expect(find.text('Office Dashboard'), findsWidgets);
    expect(find.text('Recent Tickets'), findsOneWidget);
    expect(find.textContaining('Good Moral Certificate'), findsWidgets);
  });
}

AuthUser _officeUser({required String officeName}) {
  return AuthUser(
    id: 'office-1',
    email: 'office@example.edu',
    fullName: 'Office Staff',
    role: 'office',
    officeId: 'office-1',
    officeName: officeName,
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
