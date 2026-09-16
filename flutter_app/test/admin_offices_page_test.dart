import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_management_pages.dart';
import 'package:aska_piyu/services/auth_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Map<String, dynamic> officeJson({
    required String id,
    required String name,
    String? category,
  }) {
    return {
      'id': id,
      'name': name,
      if (category != null) 'service_category': category,
    };
  }

  Map<String, dynamic> userJson({
    required String id,
    required String name,
    required String email,
    required String officeId,
    String officeName = '',
  }) {
    return {
      'id': id,
      'full_name': name,
      'email': email,
      'role': 'office',
      'office_id': officeId,
      'office_name': officeName,
      'is_active': true,
      'created_at': '2026-09-13T08:00:00Z',
    };
  }

  List<Map<String, dynamic>> sampleOffices() {
    return [
      officeJson(id: 'o1', name: 'Accounting Unit', category: 'Administrative'),
      officeJson(id: 'o2', name: 'Alumni Office', category: 'Student Services'),
      officeJson(id: 'o3', name: "Cashier's Office", category: 'Finance'),
      officeJson(
        id: 'o4',
        name: 'Guidance and Counseling Center',
        category: 'Student Services',
      ),
      officeJson(
        id: 'o5',
        name: 'Human Resource Management Office',
        category: 'Administrative',
      ),
      officeJson(
        id: 'o6',
        name: 'Information and Communications Technology Unit',
        category: 'IT Services',
      ),
      officeJson(id: 'o7', name: 'Office of Student Affairs', category: 'Student Services'),
      officeJson(id: 'o8', name: 'Office of the Registrar', category: 'Academic'),
      officeJson(id: 'o9', name: 'Testing Center', category: 'Academic'),
      officeJson(id: 'o10', name: 'University Library', category: 'Academic'),
    ];
  }

  List<Map<String, dynamic>> sampleUsers() {
    return [
      userJson(
        id: 's1',
        name: 'Ana Cruz',
        email: 'ana.cruz@example.edu',
        officeId: 'o1',
        officeName: 'Accounting Unit',
      ),
      userJson(
        id: 's2',
        name: 'Ben Reyes',
        email: 'ben.reyes@example.edu',
        officeId: 'o2',
        officeName: 'Alumni Office',
      ),
      userJson(
        id: 's3',
        name: 'Cara Lim',
        email: 'cara.lim@example.edu',
        officeId: 'o3',
        officeName: "Cashier's Office",
      ),
      userJson(
        id: 's4',
        name: 'Dan Ong',
        email: 'dan.ong@example.edu',
        officeId: 'o3',
        officeName: "Cashier's Office",
      ),
      userJson(
        id: 's5',
        name: 'Ella Tan',
        email: 'ella.tan@example.edu',
        officeId: 'o3',
        officeName: "Cashier's Office",
      ),
    ];
  }

  Map<String, dynamic> sampleStats() {
    return {
      'total': 40,
      'open': 10,
      'in_progress': 8,
      'resolved': 12,
      'closed': 10,
      'high_priority': 3,
      'by_office': {
        'Accounting Unit': 11,
        'Alumni Office': 0,
        "Cashier's Office": 5,
        'Guidance and Counseling Center': 3,
        'Human Resource Management Office': 1,
        'Information and Communications Technology Unit': 7,
        'Office of Student Affairs': 2,
        'Office of the Registrar': 12,
        'Testing Center': 4,
        'University Library': 6,
      },
      'by_priority': const <String, int>{},
      'by_category': const <String, int>{},
    };
  }

  Future<void> pumpOffices(
    WidgetTester tester, {
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? offices,
    List<Map<String, dynamic>>? users,
    Map<String, dynamic>? stats,
    Future<Map<String, dynamic>> Function({
      required String name,
      required String serviceCategory,
      required String description,
    })? debugCreateOffice,
    Future<void> Function(String officeId)? debugDeleteOffice,
    Future<Map<String, dynamic>> Function({
      required String fullName,
      required String email,
      required String password,
      required String officeId,
    })? debugCreateStaff,
    Future<void> Function(String userId)? debugDeleteStaff,
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
          home: AdminOfficesPage(
            debugOffices: offices ?? sampleOffices(),
            debugOfficeUsers: users ?? sampleUsers(),
            debugStats: stats ?? sampleStats(),
            debugCreateOffice: debugCreateOffice,
            debugDeleteOffice: debugDeleteOffice,
            debugCreateStaff: debugCreateStaff,
            debugDeleteStaff: debugDeleteStaff,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('Admin Offices page loads the compact management table',
      (tester) async {
    await pumpOffices(tester);

    expect(find.byKey(const Key('admin-offices-page')), findsOneWidget);
    expect(find.text('ORGANIZATION'), findsOneWidget);
    expect(find.text('Offices'), findsWidgets);
    expect(
      find.text('Create routing offices, assign staff logins, and review ticket load.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('admin-offices-add')), findsOneWidget);
    expect(find.text('Add Office'), findsOneWidget);
    expect(find.text('OFFICE NAME'), findsOneWidget);
    expect(find.text('CATEGORY'), findsOneWidget);
    expect(find.text('STAFF LOGINS'), findsOneWidget);
    expect(find.text('OPEN TICKETS'), findsOneWidget);
    expect(find.text('ACTIONS'), findsOneWidget);
    expect(find.text('Campus offices'), findsNothing);
    expect(find.text('Refresh'), findsNothing);
    expect(find.text('ana.cruz@example.edu'), findsNothing);
  });

  testWidgets('summary cards use live office, staff, and open-ticket counts',
      (tester) async {
    await pumpOffices(tester);

    expect(
      find.descendant(
        of: find.byKey(const Key('admin-offices-stat-total')),
        matching: find.text('10'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-offices-stat-staff')),
        matching: find.text('5'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-offices-stat-open')),
        matching: find.text('10'),
      ),
      findsOneWidget,
    );
    expect(find.text('Total Offices'), findsOneWidget);
    expect(find.text('Staff Logins'), findsOneWidget);
    expect(find.text('Open Tickets'), findsWidgets);
  });

  testWidgets('search filters offices by name', (tester) async {
    await pumpOffices(tester);

    await tester.enterText(
      find.byKey(const Key('admin-offices-search')),
      'Alumni',
    );
    await tester.pump();

    expect(find.text('Alumni Office'), findsOneWidget);
    expect(find.text('Accounting Unit'), findsNothing);
    expect(find.text("Cashier's Office"), findsNothing);
    expect(find.text('Showing 1 to 1 of 1 offices'), findsOneWidget);
  });

  testWidgets('search filters offices by category', (tester) async {
    await pumpOffices(tester);

    await tester.enterText(
      find.byKey(const Key('admin-offices-search')),
      'Finance',
    );
    await tester.pump();

    expect(find.text("Cashier's Office"), findsOneWidget);
    expect(find.text('Alumni Office'), findsNothing);
    expect(find.text('Showing 1 to 1 of 1 offices'), findsOneWidget);
  });

  testWidgets('pagination pages offices and follows search results',
      (tester) async {
    await pumpOffices(tester);

    expect(find.text('Showing 1 to 7 of 10 offices'), findsOneWidget);
    expect(find.text('Accounting Unit'), findsOneWidget);
    expect(find.text('University Library'), findsNothing);

    await tester.tap(find.text('Next'));
    await tester.pump();

    expect(find.text('Showing 8 to 10 of 10 offices'), findsOneWidget);
    expect(find.text('University Library'), findsOneWidget);
    expect(find.text('Accounting Unit'), findsNothing);

    await tester.enterText(
      find.byKey(const Key('admin-offices-search')),
      'Office',
    );
    await tester.pump();

    expect(find.text('Alumni Office'), findsOneWidget);
    expect(find.text("Cashier's Office"), findsOneWidget);
    expect(find.text('Human Resource Management Office'), findsOneWidget);
    expect(find.text('Office of Student Affairs'), findsOneWidget);
    expect(find.text('Office of the Registrar'), findsOneWidget);
    expect(find.text('University Library'), findsNothing);
    expect(find.text('Showing 1 to 5 of 5 offices'), findsOneWidget);
  });

  testWidgets('Add Office remains functional', (tester) async {
    var created = false;
    await pumpOffices(
      tester,
      debugCreateOffice: ({
        required name,
        required serviceCategory,
        required description,
      }) async {
        created = true;
        return officeJson(
          id: 'o-new',
          name: name,
          category: serviceCategory,
        );
      },
    );

    await tester.tap(find.byKey(const Key('admin-offices-add')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Add campus office'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('admin-offices-create-name')),
      'Zeta Office',
    );
    await tester.enterText(
      find.byKey(const Key('admin-offices-create-category')),
      'Academic',
    );
    await tester.tap(find.byKey(const Key('admin-offices-create-submit')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(created, isTrue);
    expect(find.text('Office created: Zeta Office'), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('admin-offices-search')),
      'Zeta',
    );
    await tester.pump();
    expect(find.byKey(const Key('admin-offices-row-o-new')), findsOneWidget);
    expect(find.text('Zeta Office'), findsWidgets);
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-offices-stat-total')),
        matching: find.text('11'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('Edit opens manage-office staff interface', (tester) async {
    await pumpOffices(tester);

    await tester.tap(find.byKey(const Key('admin-offices-edit-o1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.byKey(const Key('admin-offices-manage-drawer')), findsOneWidget);
    expect(find.text('Manage Office'), findsOneWidget);
    expect(find.byKey(const Key('admin-offices-manage-name')), findsOneWidget);
    expect(find.text('Ana Cruz'), findsOneWidget);
    expect(find.text('ana.cruz@example.edu'), findsOneWidget);
    expect(find.byKey(const Key('admin-offices-add-staff')), findsOneWidget);
    expect(
      find.byKey(const Key('admin-offices-remove-staff-s1')),
      findsOneWidget,
    );
  });

  testWidgets('Add Staff remains functional from Edit', (tester) async {
    var created = false;
    await pumpOffices(
      tester,
      debugCreateStaff: ({
        required fullName,
        required email,
        required password,
        required officeId,
      }) async {
        created = true;
        expect(officeId, 'o1');
        return userJson(
          id: 's-new',
          name: fullName,
          email: email,
          officeId: officeId,
          officeName: 'Accounting Unit',
        );
      },
    );

    await tester.tap(find.byKey(const Key('admin-offices-edit-o1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.byKey(const Key('admin-offices-add-staff')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Create office account'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('admin-offices-staff-name')),
      'New Staff',
    );
    await tester.enterText(
      find.byKey(const Key('admin-offices-staff-email')),
      'new.staff@example.edu',
    );
    await tester.enterText(
      find.byKey(const Key('admin-offices-staff-password')),
      'password123',
    );
    await tester.tap(find.byKey(const Key('admin-offices-staff-submit')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(created, isTrue);
    expect(find.text('New Staff'), findsWidgets);
    expect(
      find.byKey(const Key('admin-offices-remove-staff-s-new')),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-offices-stat-staff')),
        matching: find.text('6'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('Remove Staff remains functional from Edit', (tester) async {
    var removedId = '';
    await pumpOffices(
      tester,
      debugDeleteStaff: (userId) async {
        removedId = userId;
      },
    );

    await tester.tap(find.byKey(const Key('admin-offices-edit-o1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.byKey(const Key('admin-offices-remove-staff-s1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Remove staff account?'), findsOneWidget);
    await tester.tap(find.widgetWithText(ElevatedButton, 'Delete'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(removedId, 's1');
    expect(find.text('Ana Cruz'), findsNothing);
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-offices-stat-staff')),
        matching: find.text('4'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('Delete Office confirmation remains functional', (tester) async {
    var deletedId = '';
    await pumpOffices(
      tester,
      debugDeleteOffice: (officeId) async {
        deletedId = officeId;
      },
    );

    await tester.tap(find.byKey(const Key('admin-offices-delete-o2')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('Delete office?'), findsOneWidget);

    await tester.tap(find.text('Cancel'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(deletedId, isEmpty);
    expect(find.text('Alumni Office'), findsOneWidget);

    await tester.tap(find.byKey(const Key('admin-offices-delete-o2')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.tap(find.widgetWithText(ElevatedButton, 'Delete'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(deletedId, 'o2');
    expect(find.text('Alumni Office'), findsNothing);
    expect(find.text('Office deleted: Alumni Office'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('admin-offices-stat-total')),
        matching: find.text('9'),
      ),
      findsOneWidget,
    );
  });

  testWidgets('backend delete rejection is displayed clearly', (tester) async {
    await pumpOffices(
      tester,
      debugDeleteOffice: (officeId) async {
        throw StateError(
          'Cannot delete office while tickets or staff still reference it.',
        );
      },
    );

    await tester.tap(find.byKey(const Key('admin-offices-delete-o3')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.tap(find.widgetWithText(ElevatedButton, 'Delete'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byKey(const Key('admin-offices-delete-error')), findsOneWidget);
    expect(
      find.text(
        'Cannot delete office while tickets or staff still reference it.',
      ),
      findsOneWidget,
    );
    expect(find.text("Cashier's Office"), findsOneWidget);
  });

  testWidgets('narrow layout has no overflow', (tester) async {
    await pumpOffices(tester, size: const Size(400, 900));

    expect(tester.takeException(), isNull);
    expect(find.byKey(const Key('admin-offices-page')), findsOneWidget);
    expect(find.text('Accounting Unit'), findsOneWidget);
    expect(find.text('Add Office'), findsOneWidget);
    expect(find.text('OFFICE NAME'), findsNothing);

    await tester.tap(find.byKey(const Key('admin-offices-edit-o1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(tester.takeException(), isNull);
    expect(find.text('Manage Office'), findsOneWidget);
  });

  testWidgets('Office workspace is unaffected by the Admin Offices redesign',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(1400, 1000));
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
          home: OfficeDashboardPage(
            debugTickets: [
              {
                'ticket_id': 'TK-OPEN-1',
                'id': 'TK-OPEN-1',
                'user_id': 'user-1',
                'user_name': 'Ana Santos',
                'user_email': 'ana@example.edu',
                'original_question': 'How do I request a Good Moral Certificate?',
                'description': 'How do I request a Good Moral Certificate?',
                'status': 'Open',
                'priority': 'Medium',
                'category': 'Student Records',
                'assigned_office': 'College of Computer Studies (CCS)',
                'assigned_office_name': 'College of Computer Studies (CCS)',
                'created_at': '2026-09-12T08:00:00Z',
                'updated_at': '2026-09-12T08:00:00Z',
                'messages': const <Map<String, dynamic>>[],
              },
            ],
            debugNow: DateTime(2026, 9, 13, 10, 24),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('WELCOME BACK'), findsOneWidget);
    expect(find.text('Office Dashboard'), findsWidgets);
    expect(find.text('Recent Tickets'), findsOneWidget);
    expect(find.text('Add Office'), findsNothing);
    expect(find.text('ORGANIZATION'), findsNothing);
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
    officeName: 'College of Computer Studies (CCS)',
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
