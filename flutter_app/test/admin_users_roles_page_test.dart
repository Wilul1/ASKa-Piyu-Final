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
    String? officeId,
    String? officeName,
    bool isActive = true,
    String createdAt = '2026-09-13T08:00:00Z',
  }) {
    return {
      'id': id,
      'full_name': name,
      'email': email,
      'role': role,
      'office_id': officeId,
      'office_name': officeName,
      'is_active': isActive,
      'created_at': createdAt,
    };
  }

  List<Map<String, dynamic>> sampleOffices() {
    return [
      {'id': 'osa', 'name': 'Office of Student Affairs'},
      {'id': 'registrar', 'name': 'Office of the Registrar'},
      {'id': 'admissions', 'name': 'Admissions Office'},
      {'id': 'guidance', 'name': 'Guidance Office'},
      {'id': 'academic', 'name': 'Academic Affairs'},
    ];
  }

  List<Map<String, dynamic>> sampleUsers() {
    return [
      userJson(
        id: 'u-student-1',
        name: 'John Dela Cruz',
        email: 'john.dela.cruz@lspu.edu.ph',
        role: 'student',
      ),
      userJson(
        id: 'u-student-2',
        name: 'Maria Santos',
        email: 'maria.santos@lspu.edu.ph',
        role: 'student',
      ),
      userJson(
        id: 'u-student-3',
        name: 'Carlos Reyes',
        email: 'carlos.reyes@lspu.edu.ph',
        role: 'student',
      ),
      userJson(
        id: 'u-student-4',
        name: '',
        email: 'unnamed.student@lspu.edu.ph',
        role: 'student',
      ),
      userJson(
        id: 'u-student-5',
        name: 'Inactive Student',
        email: 'inactive.student@lspu.edu.ph',
        role: 'student',
        isActive: false,
      ),
      userJson(
        id: 'u-faculty-1',
        name: 'Ana Martinez',
        email: 'ana.martinez@lspu.edu.ph',
        role: 'faculty',
        officeId: 'academic',
        officeName: 'Academic Affairs',
      ),
      userJson(
        id: 'u-faculty-2',
        name: 'Faculty No Office',
        email: 'faculty.none@lspu.edu.ph',
        role: 'faculty',
      ),
      userJson(
        id: 'u-office-1',
        name: 'Rhea Tan',
        email: 'rhea.tan@lspu.edu.ph',
        role: 'office',
        officeId: 'osa',
        officeName: 'Office of Student Affairs',
      ),
      userJson(
        id: 'u-office-2',
        name: 'Mark Villanueva',
        email: 'mark.villanueva@lspu.edu.ph',
        role: 'office',
        officeId: 'guidance',
        officeName: 'Guidance Office',
        isActive: false,
      ),
      userJson(
        id: 'u-office-3',
        name: 'OSA Staff Two',
        email: 'osa.staff2@lspu.edu.ph',
        role: 'office',
        officeId: 'osa',
        officeName: 'Office of Student Affairs',
      ),
      userJson(
        id: 'u-office-4',
        name: 'Registrar Staff',
        email: 'registrar.staff@lspu.edu.ph',
        role: 'office',
        officeId: 'registrar',
        officeName: 'Office of the Registrar',
      ),
      userJson(
        id: 'u-office-5',
        name: 'Admissions Staff',
        email: 'admissions.staff@lspu.edu.ph',
        role: 'office',
        officeId: 'admissions',
        officeName: 'Admissions Office',
      ),
      userJson(
        id: 'u-office-6',
        name: 'Academic Staff',
        email: 'academic.staff@lspu.edu.ph',
        role: 'office',
        officeId: 'academic',
        officeName: 'Academic Affairs',
      ),
      userJson(
        id: 'u-office-7',
        name: 'Maria Office',
        email: 'maria.office@lspu.edu.ph',
        role: 'office',
        officeId: 'osa',
        officeName: 'Office of Student Affairs',
      ),
      userJson(
        id: 'admin-1',
        name: 'Admin User',
        email: 'admin@lspu.edu.ph',
        role: 'admin',
      ),
      userJson(
        id: 'u-admin-2',
        name: 'Second Admin',
        email: 'second.admin@lspu.edu.ph',
        role: 'admin',
      ),
    ];
  }

  Future<void> pumpPage(
    WidgetTester tester, {
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? users,
    List<Map<String, dynamic>>? offices,
    String? error,
    Future<Map<String, dynamic>> Function({
      required String fullName,
      required String email,
      required String password,
      required String officeId,
    })? debugCreateOfficeAccount,
    Future<Map<String, dynamic>> Function({
      required String userId,
      required bool isActive,
    })? debugSetActive,
    Future<Map<String, dynamic>> Function({
      required String userId,
      required String newPassword,
    })? debugResetPassword,
    Future<void> Function(String userId)? debugDeleteUser,
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
          home: AdminUsersRolesPage(
            debugUsers: users ?? sampleUsers(),
            debugOffices: offices ?? sampleOffices(),
            debugError: error,
            debugCreateOfficeAccount: debugCreateOfficeAccount,
            debugSetActive: debugSetActive,
            debugResetPassword: debugResetPassword,
            debugDeleteUser: debugDeleteUser,
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

  testWidgets('Users & Roles loads the compact management table', (
    tester,
  ) async {
    await pumpPage(tester);

    expect(find.byKey(const Key('admin-users-roles-page')), findsOneWidget);
    expect(find.text('Users & Roles'), findsWidgets);
    expect(
      find.text('Manage user accounts, roles, and office access for the system.'),
      findsOneWidget,
    );
    expect(find.text('+ Add Account'), findsOneWidget);
    expect(find.text('NAME'), findsOneWidget);
    expect(find.text('EMAIL'), findsOneWidget);
    expect(find.text('ROLE'), findsOneWidget);
    expect(find.text('OFFICE'), findsOneWidget);
    expect(find.text('STATUS'), findsOneWidget);
    expect(find.text('ACTIONS'), findsOneWidget);
    expect(find.text('John Dela Cruz'), findsOneWidget);
    expect(find.text('Create office account'), findsNothing);
    expect(find.text('Create faculty account'), findsNothing);
  });

  testWidgets('summary cards use live account counts', (tester) async {
    await pumpPage(tester);

    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-stat-students')),
        matching: find.text('5'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-stat-faculty')),
        matching: find.text('2'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-stat-office')),
        matching: find.text('7'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-stat-admins')),
        matching: find.text('2'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('search by name is case-insensitive', (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.byKey(const Key('admin-users-search')),
      'MARIA SANTOS',
    );
    await tester.pump();

    expect(find.byKey(const Key('admin-users-row-u-student-2')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-student-1')), findsNothing);
    expect(find.text('Showing 1–1 of 1 accounts'), findsOneWidget);
  });

  testWidgets('search by email is case-insensitive', (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.byKey(const Key('admin-users-search')),
      'RHEA.TAN@LSPU.EDU.PH',
    );
    await tester.pump();

    expect(find.byKey(const Key('admin-users-row-u-office-1')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-student-1')), findsNothing);
  });

  testWidgets('role filter uses actual backend roles', (tester) async {
    await pumpPage(tester);
    await chooseDropdown(
      tester,
      key: const Key('admin-users-role-filter'),
      option: 'Faculty',
    );

    expect(find.byKey(const Key('admin-users-row-u-faculty-1')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-faculty-2')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-student-1')), findsNothing);
    expect(find.text('Showing 1–2 of 2 accounts'), findsOneWidget);
  });

  testWidgets('office filter returns only associated accounts', (tester) async {
    await pumpPage(tester);
    await chooseDropdown(
      tester,
      key: const Key('admin-users-office-filter'),
      option: 'Office of Student Affairs',
    );

    expect(find.byKey(const Key('admin-users-row-u-office-1')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-office-3')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-office-7')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-student-1')), findsNothing);
    expect(find.byKey(const Key('admin-users-row-admin-1')), findsNothing);
    expect(find.text('Showing 1–3 of 3 accounts'), findsOneWidget);
  });

  testWidgets('status filter distinguishes Active and Inactive', (tester) async {
    await pumpPage(tester);
    await chooseDropdown(
      tester,
      key: const Key('admin-users-status-filter'),
      option: 'Inactive',
    );

    expect(find.byKey(const Key('admin-users-row-u-student-5')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-office-2')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-student-1')), findsNothing);
    expect(find.text('Showing 1–2 of 2 accounts'), findsOneWidget);
  });

  testWidgets('filters compose with AND semantics', (tester) async {
    await pumpPage(tester);
    await chooseDropdown(
      tester,
      key: const Key('admin-users-role-filter'),
      option: 'Office Staff',
    );
    await chooseDropdown(
      tester,
      key: const Key('admin-users-office-filter'),
      option: 'Office of Student Affairs',
    );
    await chooseDropdown(
      tester,
      key: const Key('admin-users-status-filter'),
      option: 'Active',
    );
    await tester.enterText(find.byKey(const Key('admin-users-search')), 'maria');
    await tester.pump();

    expect(find.byKey(const Key('admin-users-row-u-office-7')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-office-1')), findsNothing);
    expect(find.byKey(const Key('admin-users-row-u-student-2')), findsNothing);
    expect(find.text('Showing 1–1 of 1 accounts'), findsOneWidget);
  });

  testWidgets('Clear Filters restores the full list and page 1', (
    tester,
  ) async {
    await pumpPage(tester);
    await tester.enterText(find.byKey(const Key('admin-users-search')), 'maria');
    await tester.pump();
    await chooseDropdown(
      tester,
      key: const Key('admin-users-role-filter'),
      option: 'Student',
    );
    expect(find.text('Showing 1–1 of 1 accounts'), findsOneWidget);

    await tester.tap(find.byKey(const Key('admin-users-clear-filters')));
    await tester.pump();

    expect(find.text('Showing 1–7 of 16 accounts'), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-student-1')), findsOneWidget);
  });

  testWidgets('pagination and search/filter reset to page 1', (tester) async {
    await pumpPage(tester);

    expect(find.text('Showing 1–7 of 16 accounts'), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-student-1')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-office-2')), findsNothing);

    await tester.tap(find.text('Next'));
    await tester.pump();
    expect(find.text('Showing 8–14 of 16 accounts'), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-office-2')), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-u-student-1')), findsNothing);

    await tester.enterText(find.byKey(const Key('admin-users-search')), 'admin');
    await tester.pump();
    expect(find.text('Showing 1–2 of 2 accounts'), findsOneWidget);
    expect(find.byKey(const Key('admin-users-row-admin-1')), findsOneWidget);
  });

  testWidgets('role and status badges render for real values', (tester) async {
    await pumpPage(tester);

    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-role-u-student-1')),
        matching: find.text('Student'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-role-u-faculty-1')),
        matching: find.text('Faculty'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-status-u-student-1')),
        matching: find.text('Active'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('inactive badge and missing office fallback render', (
    tester,
  ) async {
    await pumpPage(tester);
    await tester.tap(find.text('Next'));
    await tester.pump();

    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-status-u-office-2')),
        matching: find.text('Inactive'),
      ),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const Key('admin-users-clear-filters')));
    await tester.pump();
    expect(find.text('John Dela Cruz'), findsOneWidget);
    expect(find.text('—'), findsWidgets);
  });

  testWidgets('View opens account management with real actions', (
    tester,
  ) async {
    var active = true;
    String? resetFor;
    await pumpPage(
      tester,
      debugSetActive: ({required userId, required isActive}) async {
        active = isActive;
        return userJson(
          id: 'u-office-1',
          name: 'Rhea Tan',
          email: 'rhea.tan@lspu.edu.ph',
          role: 'office',
          officeId: 'osa',
          officeName: 'Office of Student Affairs',
          isActive: isActive,
        );
      },
      debugResetPassword: ({required userId, required newPassword}) async {
        resetFor = '$userId:$newPassword';
        return userJson(
          id: 'u-office-1',
          name: 'Rhea Tan',
          email: 'rhea.tan@lspu.edu.ph',
          role: 'office',
          officeId: 'osa',
          officeName: 'Office of Student Affairs',
        );
      },
      debugDeleteUser: (userId) async {},
    );

    await tester.enterText(find.byKey(const Key('admin-users-search')), 'rhea tan');
    await tester.pump();
    await tester.tap(find.byKey(const Key('admin-users-view-u-office-1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.byKey(const Key('admin-users-manage-drawer')), findsOneWidget);
    expect(find.text('Account Details'), findsOneWidget);
    expect(find.text('Rhea Tan'), findsWidgets);
    expect(find.text('rhea.tan@lspu.edu.ph'), findsWidgets);
    expect(find.text('Deactivate account'), findsOneWidget);
    expect(find.text('Reset password'), findsWidgets);
    expect(find.text('Delete account'), findsOneWidget);
    expect(find.text('Current password'), findsNothing);

    await tester.tap(find.byKey(const Key('admin-users-toggle-active')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(active, isFalse);

    await tester.enterText(
      find.byKey(const Key('admin-users-reset-password')),
      'TempPass1234',
    );
    await tester.tap(find.byKey(const Key('admin-users-reset-submit')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(resetFor, 'u-office-1:TempPass1234');
    expect(find.text('TempPass1234'), findsNothing);
  });

  testWidgets('self-account deactivate and delete stay disabled', (
    tester,
  ) async {
    await pumpPage(tester);
    await tester.enterText(find.byKey(const Key('admin-users-search')), 'admin@');
    await tester.pump();
    await tester.tap(find.byKey(const Key('admin-users-view-admin-1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    final deactivate = tester.widget<ElevatedButton>(
      find.byKey(const Key('admin-users-toggle-active')),
    );
    final delete = tester.widget<OutlinedButton>(
      find.byKey(const Key('admin-users-delete')),
    );
    expect(deactivate.onPressed, isNull);
    expect(delete.onPressed, isNull);
    expect(find.text('You cannot disable your own account.'), findsOneWidget);
  });

  testWidgets('Add Account exposes only office staff creation', (tester) async {
    Map<String, String>? created;
    await pumpPage(
      tester,
      debugCreateOfficeAccount: ({
        required fullName,
        required email,
        required password,
        required officeId,
      }) async {
        created = {
          'fullName': fullName,
          'email': email,
          'password': password,
          'officeId': officeId,
        };
        return userJson(
          id: 'u-office-new',
          name: fullName,
          email: email,
          role: 'office',
          officeId: officeId,
          officeName: 'Office of Student Affairs',
        );
      },
    );

    await tester.tap(find.byKey(const Key('admin-users-add')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.byKey(const Key('admin-users-add-drawer')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-add-drawer')),
        matching: find.text('Office Staff'),
      ),
      findsWidgets,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-add-drawer')),
        matching: find.text('Student'),
      ),
      findsNothing,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-add-drawer')),
        matching: find.text('Faculty'),
      ),
      findsNothing,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-users-add-drawer')),
        matching: find.text('Admin'),
      ),
      findsNothing,
    );
    expect(find.text('Create faculty account'), findsNothing);

    await tester.enterText(
      find.byKey(const Key('admin-users-add-name')),
      'New Staff',
    );
    await tester.enterText(
      find.byKey(const Key('admin-users-add-email')),
      'new.staff@lspu.edu.ph',
    );
    await tester.enterText(
      find.byKey(const Key('admin-users-add-password')),
      'TempPass1234',
    );
    await tester.tap(find.byKey(const Key('admin-users-add-submit')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(created?['fullName'], 'New Staff');
    expect(created?['email'], 'new.staff@lspu.edu.ph');
    expect(created?['password'], 'TempPass1234');
    expect(created?['officeId'], 'academic');
    expect(find.text('Office account created for new.staff@lspu.edu.ph'), findsOneWidget);
  });

  testWidgets('empty list is explained', (tester) async {
    await pumpPage(tester, users: const []);
    expect(find.text('No accounts yet'), findsOneWidget);
  });

  testWidgets('empty search/filter state is explained', (tester) async {
    await pumpPage(tester);
    await tester.enterText(
      find.byKey(const Key('admin-users-search')),
      'zzzz-no-match',
    );
    await tester.pump();
    expect(find.text('No matching accounts'), findsOneWidget);
    expect(find.byKey(const Key('admin-users-pager')), findsNothing);
  });

  testWidgets('API error state is displayed', (tester) async {
    await pumpPage(
      tester,
      users: const [],
      error: 'Could not load users.',
    );
    expect(find.byKey(const Key('admin-users-roles-error')), findsOneWidget);
    expect(find.text('Could not load users.'), findsOneWidget);
  });

  testWidgets('narrow layout has no overflow', (tester) async {
    await pumpPage(tester, size: const Size(400, 900));

    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('admin-users-roles-page')), findsOneWidget);
    expect(find.text('NAME'), findsNothing);
    await tester.scrollUntilVisible(
      find.byKey(const Key('admin-users-row-u-student-1')),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('John Dela Cruz'), findsOneWidget);
    expect(find.text('View'), findsWidgets);
  });

  testWidgets('Office Account page remains unaffected', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1400, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(
      service: _FakeAuthService(_officeUser()),
    );
    await controller.login(
      const LoginRequest(email: 'office@example.edu', password: 'password'),
    );

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: OfficeFacultyAccountsPage(
            debugUsers: [
              userJson(
                id: 'staff-1',
                name: 'Maria Santos',
                email: 'maria.santos@example.edu',
                role: 'office',
                officeId: 'office-1',
                officeName: 'Office of Student Affairs (OSA)',
              ),
              userJson(
                id: 'faculty-1',
                name: 'Ana Reyes',
                email: 'ana.reyes@example.edu',
                role: 'faculty',
                officeId: 'office-1',
                officeName: 'Office of Student Affairs (OSA)',
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('USER ACCOUNTS'), findsOneWidget);
    expect(find.text('Office Staff Accounts'), findsOneWidget);
    expect(find.text('Maria Santos'), findsOneWidget);
    expect(find.text('Add Account'), findsOneWidget);
    expect(find.byKey(const Key('admin-users-roles-page')), findsNothing);
    expect(find.text('Manage user accounts, roles, and office access for the system.'), findsNothing);
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
