// Widget tests for the optional "Office (optional)" direct-selection
// dropdown added to CreateTicketForm. Automatic Routing (no dropdown
// interaction) must remain the default and must not send any student
// manual-office-selection fields -- see backend/app/services/ticketing.py's
// explicit_office_selected for the corresponding server-side contract these
// UI states are expected to drive.
//
// CreateTicketForm fetches GET /tickets/offices over the network on mount
// with no override seam on ApiClient itself, so these tests use the
// existing debugOffices/debugTickets-style seeded-data convention (see
// OfficeDashboardPage.debugTickets in admin_management_pages.dart) to avoid
// needing a live backend. The one failure-resilience test intentionally
// omits debugOffices so the real (failing, no-backend-in-test) network path
// exercises the office-list-load-failure behavior directly.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/my_tickets_page.dart';
import 'package:aska_piyu/services/auth_service.dart';

const _automaticLabel = 'Automatic routing — Let ASKa-Piyu choose';

AuthUser _studentUser() {
  return const AuthUser(
    id: 'student-1',
    email: 'student@example.edu',
    fullName: 'Test Student',
    role: 'student',
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
    return AuthResponse(
      accessToken: 'token-${user.role}',
      tokenType: 'bearer',
      user: user,
    );
  }
}

final _sampleOffices = <Map<String, dynamic>>[
  {'id': 'office-registrar', 'name': 'Registrar'},
  {'id': 'office-osas', 'name': 'OSAS'},
  {'id': 'office-ccs', 'name': 'CCS'},
];

Future<void> _pumpForm(
  WidgetTester tester, {
  List<Map<String, dynamic>>? debugOffices,
}) async {
  final controller = AuthController(service: _FakeAuthService(_studentUser()));
  await controller.login(
    const LoginRequest(email: 'student@example.edu', password: 'password'),
  );

  await tester.pumpWidget(
    AuthScope(
      controller: controller,
      child: MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CreateTicketForm(
              onCreated: (_) {},
              debugOffices: debugOffices,
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('Automatic Routing shown by default', (tester) async {
    await _pumpForm(tester, debugOffices: _sampleOffices);

    expect(find.text('Office (optional)'), findsOneWidget);
    expect(find.text(_automaticLabel), findsOneWidget);
  });

  testWidgets('dropdown contains offices', (tester) async {
    await _pumpForm(tester, debugOffices: _sampleOffices);

    await tester.tap(find.byType(DropdownButtonFormField<String?>));
    await tester.pumpAndSettle();

    expect(find.text('Registrar'), findsOneWidget);
    expect(find.text('OSAS'), findsOneWidget);
    expect(find.text('CCS'), findsOneWidget);
    // Automatic option also appears once more inside the open menu.
    expect(find.text(_automaticLabel), findsWidgets);
  });

  testWidgets('choosing office changes selection', (tester) async {
    await _pumpForm(tester, debugOffices: _sampleOffices);

    await tester.tap(find.byType(DropdownButtonFormField<String?>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Registrar').last);
    await tester.pumpAndSettle();

    // The field now displays the selected office as its current value.
    final field = tester.widget<DropdownButtonFormField<String?>>(
      find.byType(DropdownButtonFormField<String?>),
    );
    expect(field.initialValue, 'office-registrar');
  });

  testWidgets('returning to Automatic clears manual office selection',
      (tester) async {
    await _pumpForm(tester, debugOffices: _sampleOffices);

    await tester.tap(find.byType(DropdownButtonFormField<String?>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OSAS').last);
    await tester.pumpAndSettle();

    var field = tester.widget<DropdownButtonFormField<String?>>(
      find.byType(DropdownButtonFormField<String?>),
    );
    expect(field.initialValue, 'office-osas');

    await tester.tap(find.byType(DropdownButtonFormField<String?>));
    await tester.pumpAndSettle();
    await tester.tap(find.text(_automaticLabel).last);
    await tester.pumpAndSettle();

    field = tester.widget<DropdownButtonFormField<String?>>(
      find.byType(DropdownButtonFormField<String?>),
    );
    expect(field.initialValue, isNull);
  });

  testWidgets('office-list failure still permits automatic submission',
      (tester) async {
    // No debugOffices seeded -- GET /tickets/offices genuinely fails in
    // this sandbox (no backend). Automatic Routing must remain usable.
    await _pumpForm(tester);

    // Automatic Routing (the default) must remain fully usable even though
    // the office list never loaded -- the whole form still renders intact.
    expect(find.text(_automaticLabel), findsOneWidget);
    expect(find.byType(DropdownButtonFormField<String?>), findsOneWidget);
    expect(find.byType(TextFormField), findsNWidgets(2)); // Subject + Description
    expect(find.text('Submit Ticket'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('existing Subject/Description/Attachment behavior remains intact',
      (tester) async {
    await _pumpForm(tester, debugOffices: _sampleOffices);

    expect(find.text('Subject'), findsOneWidget);
    expect(find.text('Description'), findsOneWidget);
    expect(find.text('Attachment (optional)'), findsOneWidget);
    expect(find.text('Clear'), findsOneWidget);
    expect(find.text('Submit Ticket'), findsOneWidget);
  });
}
