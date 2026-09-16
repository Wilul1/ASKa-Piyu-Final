import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/admin_article_models.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_management_pages.dart';
import 'package:aska_piyu/screens/my_tickets_page.dart';
import 'package:aska_piyu/services/admin_article_service.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/widgets/admin_kb_article_shared.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const phoneSizes = <Size>[
    Size(360, 800),
    Size(390, 844),
    Size(412, 915),
  ];

  Future<AuthController> signIn(String role) async {
    final controller = AuthController(service: _FakeAuthService(_user(role)));
    await controller.login(const LoginRequest(
      email: 'test@example.edu',
      password: 'password',
    ));
    return controller;
  }

  Future<void> setViewport(WidgetTester tester, Size size) async {
    await tester.binding.setSurfaceSize(size);
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
  }

  void expectNoOverflow(WidgetTester tester) {
    final exception = tester.takeException();
    if (exception is FlutterError) {
      fail(exception.diagnostics.map((node) => node.toString()).join('\n'));
    }
    if (exception != null) fail('$exception');
  }

  void expectDialogFits(WidgetTester tester, Size viewport) {
    expectNoOverflow(tester);
    final dialog = find.byType(Dialog);
    expect(dialog, findsWidgets);
    final box = tester.getRect(dialog.last);
    expect(box.width, lessThanOrEqualTo(viewport.width + 0.5));
    expect(box.right, lessThanOrEqualTo(viewport.width + 0.5));
    expect(box.height, lessThanOrEqualTo(viewport.height + 0.5));
  }

  testWidgets('student reply composer stays above a narrow keyboard',
      (tester) async {
    for (final size in phoneSizes) {
      await setViewport(tester, size);
      final controller = await signIn('student');
      await tester.pumpWidget(
        AuthScope(
          controller: controller,
          child: MaterialApp(
            home: TicketDetailsPage(
              ticket: TicketEntry.fromJson({
                'ticket_id': 'TK-REPLY',
                'user_id': 'student-1',
                'user_name': 'Ana Santos',
                'original_question': 'Good moral certificate',
                'description': 'I need the steps.',
                'status': 'Open',
                'priority': 'Medium',
                'category': 'Student Records',
                'assigned_office': 'Office of Student Affairs',
                'created_at': '2026-09-13T02:24:00Z',
                'updated_at': '2026-09-13T02:24:00Z',
                'messages': const <Map<String, dynamic>>[],
              }),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.text('Good moral certificate'), findsWidgets);
      await tester.tap(find.text('Conversation').first);
      await tester.pump();

      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      await tester.pump();

      expectNoOverflow(tester);
      final composer = tester.getRect(find.byKey(const Key('student-reply-composer')));
      final send = tester.getRect(find.text('Send reply'));
      expect(composer.bottom, lessThanOrEqualTo(size.height - 300 + 1));
      expect(send.bottom, lessThanOrEqualTo(size.height - 300 + 1));
      expect(find.text('Write a reply to the office…'), findsOneWidget);

      tester.view.viewInsets = FakeViewPadding.zero;
      await tester.pump();
      expectNoOverflow(tester);
      final closed = tester.getRect(find.byKey(const Key('student-reply-composer')));
      expect(closed.bottom, greaterThan(size.height - 80));
    }
    addTearDown(() async {
      tester.view.resetViewInsets();
      tester.view.resetPhysicalSize();
      await tester.binding.setSurfaceSize(null);
    });
  });

  testWidgets('office transfer dialog fits phone widths', (tester) async {
    for (final size in phoneSizes) {
      await setViewport(tester, size);
      final controller = await signIn('office');
      await tester.pumpWidget(
        AuthScope(
          controller: controller,
          child: MaterialApp(
            home: OfficeAssignedTicketsPage(
              initialSelectedTicketId: 'TK-TRANSFER',
              debugTickets: [
                {
                  'ticket_id': 'TK-TRANSFER',
                  'user_id': 'user-1',
                  'user_name': 'Ana Santos',
                  'original_question': 'Good moral certificate',
                  'description': 'I need the steps.',
                  'status': 'Open',
                  'priority': 'Medium',
                  'category': 'Student Records',
                  'assigned_office': 'ICT Office',
                  'assigned_office_name': 'ICT Office',
                  'created_at': '2026-09-13T02:24:00Z',
                  'updated_at': '2026-09-13T02:24:00Z',
                  'messages': const <Map<String, dynamic>>[],
                },
              ],
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      final transfer = find.byTooltip('Transfer / reassign', skipOffstage: false);
      await tester.ensureVisible(transfer);
      await tester.pump();
      final transferRect = tester.getRect(transfer);
      await tester.tapAt(Offset(transferRect.center.dx, transferRect.top + 4));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('Transfer ticket'), findsOneWidget);
      expect(find.text('Apply'), findsOneWidget);
      expectDialogFits(tester, size);
    }
  });

  testWidgets('ticket-to-KB actions stay reachable on a phone', (tester) async {
    await setViewport(tester, const Size(390, 844));
    final controller = await signIn('office');
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: OfficeAssignedTicketsPage(
            debugTickets: [
              {
                'ticket_id': 'TK-KB',
                'user_id': 'user-1',
                'user_name': 'Ana Santos',
                'original_question': 'Good moral certificate',
                'description': 'I need the steps.',
                'status': 'Resolved',
                'priority': 'Medium',
                'category': 'Student Records',
                'assigned_office': 'ICT Office',
                'assigned_office_name': 'ICT Office',
                'created_at': '2026-09-13T02:24:00Z',
                'updated_at': '2026-09-13T02:24:00Z',
                'messages': [
                  {
                    'id': 'm2',
                    'ticket_id': 'TK-KB',
                    'sender_id': 'office-1',
                    'sender_role': 'office',
                    'sender_name': 'OSA',
                    'message': 'Please follow these steps.',
                    'created_at': '2026-09-13T03:00:00Z',
                    'is_internal': false,
                  },
                ],
              },
            ],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('TK-KB'));
    await tester.pump();
    await tester.tap(find.text('Add to KB'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Compose KB article'), findsOneWidget);
    expect(find.byKey(const Key('ticket-kb-publish')), findsOneWidget);
    expect(find.byKey(const Key('ticket-kb-actions')), findsOneWidget);
    expect(find.byKey(const Key('ticket-kb-cancel')), findsNothing);
    expectNoOverflow(tester);

    await tester.tap(find.byKey(const Key('ticket-kb-actions')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.byKey(const Key('ticket-kb-cancel')), findsOneWidget);
    expect(find.byKey(const Key('ticket-kb-save-draft')), findsOneWidget);
    expectNoOverflow(tester);

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    await setViewport(tester, const Size(1200, 900));
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: OfficeAssignedTicketsPage(
            initialSelectedTicketId: 'TK-KB',
            debugTickets: [
              {
                'ticket_id': 'TK-KB',
                'user_id': 'user-1',
                'user_name': 'Ana Santos',
                'original_question': 'Good moral certificate',
                'description': 'I need the steps.',
                'status': 'Resolved',
                'priority': 'Medium',
                'category': 'Student Records',
                'assigned_office': 'ICT Office',
                'assigned_office_name': 'ICT Office',
                'created_at': '2026-09-13T02:24:00Z',
                'updated_at': '2026-09-13T02:24:00Z',
                'messages': [
                  {
                    'id': 'm2',
                    'ticket_id': 'TK-KB',
                    'sender_id': 'office-1',
                    'sender_role': 'office',
                    'sender_name': 'OSA',
                    'message': 'Please follow these steps.',
                    'created_at': '2026-09-13T03:00:00Z',
                    'is_internal': false,
                  },
                ],
              },
            ],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Add to KB'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byKey(const Key('ticket-kb-actions')), findsNothing);
    expect(find.byKey(const Key('ticket-kb-cancel')), findsOneWidget);
    expect(find.byKey(const Key('ticket-kb-save-draft')), findsOneWidget);
    expect(find.byKey(const Key('ticket-kb-publish')), findsOneWidget);
    expectNoOverflow(tester);
  });

  testWidgets('admin convert and attachment dialogs fit a phone', (tester) async {
    await setViewport(tester, const Size(390, 844));
    final controller = await signIn('admin');
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: AdminAllTicketsPage(
            debugOffices: const [
              {'id': 'o1', 'name': 'Office of the Registrar'},
            ],
            debugTickets: [
              {
                'ticket_id': 'TK-ATT',
                'user_id': 'user-1',
                'user_name': 'Ana Santos',
                'user_email': 'ana@example.edu',
                'original_question': 'Excuse slip',
                'description': 'I missed class.',
                'status': 'Closed',
                'priority': 'Low',
                'category': 'Student Records',
                'assigned_office': 'Office of the Registrar',
                'assigned_office_id': 'o1',
                'created_at': '2026-09-12T08:32:00Z',
                'updated_at': '2026-09-12T08:32:00Z',
                'messages': const <Map<String, dynamic>>[],
                'attachments': [
                  {
                    'id': 'att-1',
                    'ticket_id': 'TK-ATT',
                    'original_filename': 'excuse-slip.pdf',
                    'content_type': 'application/pdf',
                    'size_bytes': 1200,
                    'download_url': '/tickets/TK-ATT/attachments/att-1',
                    'created_at': '2026-09-12T08:32:00Z',
                  },
                ],
              },
            ],
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    final view = find.byKey(
      const Key('admin-all-tickets-view-TK-ATT'),
      skipOffstage: false,
    );
    expect(view, findsOneWidget);
    await tester.ensureVisible(view);
    await tester.pump();
    await tester.tap(view);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('excuse-slip.pdf'), findsOneWidget);
    expect(find.text('application/pdf'), findsOneWidget);
    expect(find.byKey(const Key('admin-ticket-attachment-att-1')), findsOneWidget);
    expectDialogFits(tester, const Size(390, 844));

    final convert = find.text('Convert to Knowledge Base', skipOffstage: false);
    await tester.ensureVisible(convert);
    await tester.pump();
    await tester.tap(convert);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Convert to Knowledge Base'), findsWidgets);
    expect(find.text('Save draft'), findsOneWidget);
    expect(find.text('FAQ title'), findsOneWidget);
    expectDialogFits(tester, const Size(390, 844));
  });

  testWidgets('admin office account dialog fits phone widths', (tester) async {
    for (final size in phoneSizes) {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      await setViewport(tester, size);
      final controller = await signIn('admin');
      await tester.pumpWidget(
        AuthScope(
          controller: controller,
          child: MaterialApp(
            home: AdminOfficesPage(
              debugOffices: const [
                {
                  'id': 'o1',
                  'name': 'Accounting Unit',
                  'service_category': 'Administrative',
                },
              ],
              debugOfficeUsers: const [],
            ),
          ),
        ),
      );
      await tester.pump();
      final addOffice = find.byKey(
        const Key('admin-offices-add'),
        skipOffstage: false,
      );
      await tester.ensureVisible(addOffice);
      await tester.pump();
      await tester.tap(addOffice);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('Add campus office'), findsOneWidget);
      expect(find.text('Create'), findsOneWidget);
      expectDialogFits(tester, size);
      await tester.tap(find.text('Cancel'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      final edit = find.byKey(
        const Key('admin-offices-edit-o1'),
        skipOffstage: false,
      );
      await tester.ensureVisible(edit);
      await tester.pump();
      await tester.tap(edit);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));
      final addStaff = find.byKey(
        const Key('admin-offices-add-staff'),
        skipOffstage: false,
      );
      await tester.ensureVisible(addStaff);
      await tester.pump();
      await tester.tap(addStaff);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('Create office account'), findsOneWidget);
      expect(find.byKey(const Key('admin-offices-staff-name')), findsOneWidget);
      expect(find.text('Create'), findsOneWidget);
      expectDialogFits(tester, size);
    }
  });

  testWidgets('admin KB editor dialog fits a phone', (tester) async {
    await setViewport(tester, const Size(390, 844));
    final controller = await signIn('admin');
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: Builder(
            builder: (context) {
              return Scaffold(
                body: TextButton(
                  onPressed: () {
                    showDialog<void>(
                      context: context,
                      builder: (dialogContext) => AdminArticleEditor(
                        article: const AdminArticle(
                          id: 'a1',
                          title: 'Excuse slip steps',
                          category: 'Academic Policies',
                          published: false,
                          displayContent: 'Get the slip from the office.',
                        ),
                        service: AdminArticleService(
                          apiBase: 'http://localhost',
                          setAdminHeader: (_) {},
                        ),
                      ),
                    );
                  },
                  child: const Text('Open editor'),
                ),
              );
            },
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.tap(find.text('Open editor'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('Edit Article'), findsOneWidget);
    expect(find.text('Save Changes'), findsOneWidget);
    expectDialogFits(tester, const Size(390, 844));
  });
}

AuthUser _user(String role) {
  return AuthUser(
    id: '$role-1',
    email: '$role@example.edu',
    fullName: '$role User',
    role: role,
    officeId: role == 'office' ? 'office-1' : null,
    officeName: role == 'office' ? 'ICT Office' : null,
    emailVerified: true,
    createdAt: null,
    updatedAt: null,
  );
}

class _FakeAuthService extends AuthService {
  _FakeAuthService(this.user);

  final AuthUser user;
  String? _token;

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
