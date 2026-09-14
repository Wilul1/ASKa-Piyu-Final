import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_management_pages.dart';
import 'package:aska_piyu/services/auth_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Map<String, dynamic> userJson({
    required String id,
    required String name,
    required String email,
    required String role,
    bool isActive = true,
    String createdAt = '2026-09-13T08:00:00Z',
  }) {
    return {
      'id': id,
      'full_name': name,
      'email': email,
      'role': role,
      'office_id': 'office-1',
      'office_name': 'Office of Student Affairs (OSA)',
      'is_active': isActive,
      'created_at': createdAt,
    };
  }

  List<Map<String, dynamic>> sampleUsers() {
    return [
      userJson(
        id: 'staff-1',
        name: 'Maria Santos',
        email: 'maria.santos@example.edu',
        role: 'office',
      ),
      userJson(
        id: 'staff-2',
        name: 'Inactive Staff',
        email: 'inactive.staff@example.edu',
        role: 'office',
        isActive: false,
        createdAt: '2026-08-01T08:00:00Z',
      ),
      userJson(
        id: 'faculty-1',
        name: 'Ana Reyes',
        email: 'ana.reyes@example.edu',
        role: 'faculty',
      ),
      userJson(
        id: 'faculty-2',
        name: 'Inactive Faculty',
        email: 'inactive.faculty@example.edu',
        role: 'faculty',
        isActive: false,
      ),
    ];
  }

  Future<void> pumpAccount(
    WidgetTester tester, {
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? users,
    bool loading = false,
    String? error,
    String officeName = 'Office of Student Affairs (OSA)',
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
          home: OfficeFacultyAccountsPage(
            debugUsers: users,
            debugLoading: loading,
            debugError: error,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('Office Account page renders', (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    expect(find.text('USER ACCOUNTS'), findsOneWidget);
    expect(find.text('Account'), findsWidgets);
    expect(find.text('Add Account'), findsOneWidget);
    expect(find.text('Office Staff Accounts'), findsOneWidget);
    expect(find.text('Faculty Accounts'), findsOneWidget);
    expect(find.byType(Dialog), findsNothing);
  });

  testWidgets('authenticated office name appears dynamically', (tester) async {
    await pumpAccount(
      tester,
      users: sampleUsers(),
      officeName: 'Office of Student Affairs (OSA)',
    );

    expect(
      find.text(
        'Monitor and manage office staff and faculty logins for Office of Student Affairs (OSA).',
      ),
      findsOneWidget,
    );
    expect(find.textContaining('College of Computer Studies (CCS)'), findsNothing);
  });

  testWidgets('Office Staff accounts render from fixture data', (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    expect(find.text('Maria Santos'), findsOneWidget);
    expect(find.text('maria.santos@example.edu'), findsOneWidget);
    expect(find.text('Inactive Staff'), findsOneWidget);
    expect(find.text('Office Staff'), findsWidgets);
    expect(find.text('CSS'), findsNothing);
    expect(find.text('ccs@aska.local'), findsNothing);
  });

  testWidgets('Faculty accounts render from fixture data', (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    expect(find.text('Ana Reyes'), findsOneWidget);
    expect(find.text('ana.reyes@example.edu'), findsOneWidget);
    expect(find.text('Inactive Faculty'), findsOneWidget);
    expect(find.text('testing faculty'), findsNothing);
    expect(find.text('test@gmail.com'), findsNothing);
  });

  testWidgets('staff search filters independently of faculty', (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    await tester.enterText(find.byKey(const Key('office-staff-search')), 'maria');
    await tester.pump();

    expect(find.text('Maria Santos'), findsOneWidget);
    expect(find.text('Inactive Staff'), findsNothing);
    expect(find.text('Ana Reyes'), findsOneWidget);
    expect(find.text('Inactive Faculty'), findsOneWidget);
  });

  testWidgets('faculty search filters independently of staff', (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    await tester.enterText(
      find.byKey(const Key('office-faculty-search')),
      'ANA.REYES',
    );
    await tester.pump();

    expect(find.text('Ana Reyes'), findsOneWidget);
    expect(find.text('Inactive Faculty'), findsNothing);
    expect(find.text('Maria Santos'), findsOneWidget);
    expect(find.text('Inactive Staff'), findsOneWidget);
  });

  testWidgets('Active and Inactive status badges render', (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    expect(find.text('Active'), findsNWidgets(2));
    expect(find.text('Inactive'), findsNWidgets(2));
  });

  testWidgets('office account does not invent edit or deactivate actions',
      (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    expect(find.text('Edit'), findsNothing);
    expect(find.text('Deactivate'), findsNothing);
    expect(find.text('Activate'), findsNothing);
  });

  testWidgets('Add Account opens the existing staff creation dialog',
      (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    await tester.tap(find.byKey(const Key('office-add-account')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-office-staff')));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.text('New office staff login'), findsOneWidget);
    expect(find.text('Full name'), findsOneWidget);
    expect(find.text('Temporary password'), findsOneWidget);
    expect(find.text('Create staff login'), findsOneWidget);
  });

  testWidgets('Add Account opens the existing faculty creation dialog',
      (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    await tester.tap(find.byKey(const Key('office-add-account')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-office-faculty')));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    expect(find.text('New faculty login'), findsOneWidget);
    expect(find.text('Create faculty login'), findsOneWidget);
  });

  testWidgets('empty states render for staff and faculty', (tester) async {
    await pumpAccount(tester, users: const []);

    expect(find.text('No office staff accounts yet'), findsOneWidget);
    expect(find.text('No faculty accounts yet'), findsOneWidget);
    expect(find.text('Maria Santos'), findsNothing);
    expect(find.text('Ana Reyes'), findsNothing);
  });

  testWidgets('no search results state renders without fake rows',
      (tester) async {
    await pumpAccount(tester, users: sampleUsers());

    await tester.enterText(
      find.byKey(const Key('office-staff-search')),
      'no-such-staff',
    );
    await tester.pump();

    expect(find.text('No matching staff accounts'), findsOneWidget);
    expect(find.text('Maria Santos'), findsNothing);
    expect(find.text('Ana Reyes'), findsOneWidget);
  });

  testWidgets('loading state does not break layout', (tester) async {
    await pumpAccount(tester, users: const [], loading: true);

    expect(find.text('Loading accounts'), findsWidgets);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('error state does not break layout', (tester) async {
    await pumpAccount(
      tester,
      users: const [],
      error: 'Could not load users.',
    );

    expect(find.text('Could not load users.'), findsOneWidget);
    expect(find.text('No office staff accounts yet'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('narrow layout has no overflow', (tester) async {
    await pumpAccount(
      tester,
      users: sampleUsers(),
      size: const Size(400, 900),
    );

    expect(tester.takeException(), isNull);
    expect(find.text('Account'), findsWidgets);
    expect(find.text('Add Account'), findsOneWidget);
    expect(find.text('Office Staff Accounts'), findsOneWidget);
    expect(find.text('Maria Santos'), findsOneWidget);
    expect(find.text('Faculty Accounts'), findsNothing);

    await tester.tap(find.text('Faculty'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Faculty Accounts'), findsOneWidget);
    expect(find.text('Ana Reyes'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Admin Users & Roles UI is unaffected', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1400, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(
      service: _FakeAuthService(_adminUser()),
    );
    await controller.login(const LoginRequest(
      email: 'admin@example.edu',
      password: 'password',
    ));

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: const MaterialApp(home: AdminUsersRolesPage()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Users & Roles'), findsWidgets);
    expect(
      find.text(
        'Search accounts, filter by role, and create office or faculty logins.',
      ),
      findsOneWidget,
    );
    expect(find.text('Create office account'), findsOneWidget);
    expect(find.text('Create faculty account'), findsOneWidget);
    expect(find.text('USER ACCOUNTS'), findsNothing);
    expect(find.text('Office Staff Accounts'), findsNothing);
    expect(tester.takeException(), isNull);
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
    return AuthResponse(
      accessToken: 'token-${user.role}',
      tokenType: 'bearer',
      user: user,
    );
  }

  @override
  Future<AuthUser> getCurrentUser(String token) async => user;
}
