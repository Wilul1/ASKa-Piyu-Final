import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/admin_article_models.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_management_pages.dart';
import 'package:aska_piyu/screens/knowledge_article_create_page.dart';
import 'package:aska_piyu/screens/knowledge_article_edit_page.dart';
import 'package:aska_piyu/screens/knowledge_articles_page.dart';
import 'package:aska_piyu/services/auth_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Map<String, dynamic> articleJson({
    required String id,
    required String title,
    required String office,
    required String category,
    required bool published,
    String updatedAt = '2026-09-05T08:00:00Z',
    String summary = '',
  }) {
    return {
      'id': id,
      'title': title,
      'office': office,
      'category': category,
      'published': published,
      'summary': summary,
      'updated_at': updatedAt,
      'created_at': updatedAt,
    };
  }

  List<Map<String, dynamic>> adminArticles() {
    return [
      articleJson(
        id: 'a1',
        title: 'How do I get an excuse slip if I missed class?',
        office: 'Office of the Registrar',
        category: 'Academic Policies',
        published: true,
        updatedAt: '2026-09-05T08:00:00Z',
        summary: 'excuse slip missed class illness',
      ),
      articleJson(
        id: 'a2',
        title: 'Unauthorized Absences (AWOL)',
        office: 'Guidance and Counseling Center',
        category: 'Student Records',
        published: true,
        updatedAt: '2026-08-17T08:00:00Z',
      ),
      articleJson(
        id: 'a3',
        title: 'Scholarship Application Process',
        office: 'Office of Student Affairs',
        category: 'Scholarship',
        published: false,
        updatedAt: '2026-08-01T08:00:00Z',
      ),
      for (var i = 4; i <= 12; i++)
        articleJson(
          id: 'a$i',
          title: 'Policy article $i',
          office: 'Office of the Registrar',
          category: 'Enrollment',
          published: true,
          updatedAt: '2026-07-${i.toString().padLeft(2, '0')}T08:00:00Z',
        ),
    ];
  }

  List<Map<String, dynamic>> officeArticles() {
    return [
      articleJson(
        id: 'osa-1',
        title: 'OSA student activity clearance',
        office: 'Office of Student Affairs',
        category: 'Student Services',
        published: true,
      ),
      articleJson(
        id: 'osa-2',
        title: 'OSA draft handbook note',
        office: 'Office of Student Affairs',
        category: 'Student Services',
        published: false,
      ),
    ];
  }

  Future<void> pumpPage(
    WidgetTester tester, {
    required AuthUser user,
    Size size = const Size(1400, 1000),
    List<Map<String, dynamic>>? articles,
    bool loading = false,
    String? error,
    Future<AdminArticle> Function(Map<String, dynamic> payload)?
        debugCreateArticle,
    List<String>? debugOfficeNames,
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final controller = AuthController(service: _FakeAuthService(user));
    await controller.login(LoginRequest(
      email: user.email,
      password: 'password',
    ));

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: KnowledgeArticlesPage(
            debugArticles: articles,
            debugLoading: loading,
            debugError: error,
            debugCreateArticle: debugCreateArticle,
            debugOfficeNames: debugOfficeNames,
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  group('Admin Knowledge Article', () {
    testWidgets('renders header, stats, and table', (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: adminArticles());

      expect(find.text('KNOWLEDGE BASE'), findsOneWidget);
      expect(find.text('Knowledge Article'), findsWidgets);
      expect(find.text('Create Article'), findsOneWidget);
      expect(find.text('Total Articles'), findsOneWidget);
      expect(find.text('12'), findsOneWidget);
      expect(find.text('Published'), findsWidgets);
      expect(find.text('11'), findsOneWidget);
      expect(find.text('Drafts'), findsOneWidget);
      expect(find.text('1'), findsWidgets);
      expect(find.text('Categories'), findsOneWidget);
      expect(find.text('4'), findsOneWidget);
      expect(
        find.text('How do I get an excuse slip if I missed class?'),
        findsOneWidget,
      );
      expect(find.text('Office of the Registrar'), findsWidgets);
      expect(find.text('Academic Policies'), findsOneWidget);
      expect(find.text('Edit'), findsWidgets);
      expect(find.text('Delete'), findsWidgets);
    });

    testWidgets('search filters articles', (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: adminArticles());

      await tester.enterText(
        find.byKey(const Key('knowledge-article-search')),
        'excuse slip',
      );
      await tester.tap(find.byKey(const Key('knowledge-article-search-btn')));
      await tester.pump();

      expect(
        find.text('How do I get an excuse slip if I missed class?'),
        findsOneWidget,
      );
      expect(find.text('Unauthorized Absences (AWOL)'), findsNothing);
      expect(find.text('Showing 1 to 1 of 1 articles'), findsOneWidget);
    });

    testWidgets('office, category, and status filters work', (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: adminArticles());

      await tester.tap(find.byKey(const Key('knowledge-article-office-filter')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Guidance and Counseling Center').last);
      await tester.pumpAndSettle();
      expect(find.text('Unauthorized Absences (AWOL)'), findsOneWidget);
      expect(
        find.text('How do I get an excuse slip if I missed class?'),
        findsNothing,
      );

      await tester.tap(find.byKey(const Key('knowledge-article-reset')));
      await tester.pump();

      await tester.tap(find.byKey(const Key('knowledge-article-category-filter')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Scholarship').last);
      await tester.pumpAndSettle();
      expect(find.text('Scholarship Application Process'), findsOneWidget);
      expect(find.text('Unauthorized Absences (AWOL)'), findsNothing);

      await tester.tap(find.byKey(const Key('knowledge-article-reset')));
      await tester.pump();

      await tester.tap(find.byKey(const Key('knowledge-article-status-filter')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Draft').last);
      await tester.pumpAndSettle();
      expect(find.text('Scholarship Application Process'), findsOneWidget);
      expect(find.text('Draft'), findsWidgets);
      expect(
        find.text('How do I get an excuse slip if I missed class?'),
        findsNothing,
      );
    });

    testWidgets('reset restores the full list', (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: adminArticles());

      await tester.enterText(
        find.byKey(const Key('knowledge-article-search')),
        'scholarship',
      );
      await tester.tap(find.byKey(const Key('knowledge-article-search-btn')));
      await tester.pump();
      expect(find.text('Scholarship Application Process'), findsOneWidget);
      expect(find.text('Unauthorized Absences (AWOL)'), findsNothing);

      await tester.tap(find.byKey(const Key('knowledge-article-reset')));
      await tester.pump();
      expect(find.text('Unauthorized Absences (AWOL)'), findsOneWidget);
      expect(find.text('Showing 1 to 10 of 12 articles'), findsOneWidget);
    });

    testWidgets('admin actions match permissions', (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: adminArticles());

      expect(find.text('Edit'), findsWidgets);
      expect(find.text('Delete'), findsWidgets);
      await tester.tap(find.byKey(const Key('knowledge-article-delete-a1')));
      await tester.pumpAndSettle();
      expect(find.text('Delete article?'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(
        find.text('How do I get an excuse slip if I missed class?'),
        findsOneWidget,
      );
    });

    testWidgets('pagination works', (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: adminArticles());

      expect(find.text('Showing 1 to 10 of 12 articles'), findsOneWidget);
      // Sorted by updated_at desc, so the oldest July fixtures land on page 2.
      expect(find.text('Policy article 4'), findsNothing);

      await tester.ensureVisible(find.text('Next'));
      await tester.pump();
      await tester.tap(find.text('Next'));
      await tester.pump();
      expect(find.text('Showing 11 to 12 of 12 articles'), findsOneWidget);
      expect(find.text('Policy article 4'), findsOneWidget);
      expect(find.text('Policy article 5'), findsOneWidget);
      expect(
        find.text('How do I get an excuse slip if I missed class?'),
        findsNothing,
      );
    });

    testWidgets('empty, loading, and error states work', (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: const []);
      expect(find.text('No articles yet'), findsOneWidget);

      await pumpPage(
        tester,
        user: _adminUser(),
        articles: const [],
        loading: true,
      );
      expect(find.text('Loading articles'), findsOneWidget);
      expect(find.byType(LinearProgressIndicator), findsOneWidget);

      await pumpPage(
        tester,
        user: _adminUser(),
        articles: const [],
        error: 'Could not load articles.',
      );
      expect(find.text('Could not load articles.'), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
    });

    testWidgets('narrow layout has no overflow', (tester) async {
      await pumpPage(
        tester,
        user: _adminUser(),
        articles: adminArticles(),
        size: const Size(400, 900),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Knowledge Article'), findsWidgets);
      expect(find.text('Create Article'), findsOneWidget);
      expect(find.text('Edit'), findsWidgets);
    });

    testWidgets('Create Article opens the full create page', (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: adminArticles());

      await tester.tap(find.byKey(const Key('knowledge-article-create')));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.byType(KnowledgeArticleCreatePage), findsOneWidget);
      expect(find.text('Create Knowledge Article'), findsOneWidget);
      expect(find.text('Create draft'), findsNothing);
      expect(find.text('Back to Articles'), findsOneWidget);
      expect(find.byKey(const Key('knowledge-article-create-page')), findsOneWidget);
    });

    testWidgets('existing article Edit flow still opens the editor',
        (tester) async {
      await pumpPage(tester, user: _adminUser(), articles: adminArticles());

      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-edit-a1')),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-edit-a1')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.byType(KnowledgeArticleEditPage), findsOneWidget);
      expect(find.text('Create Knowledge Article'), findsNothing);
    });
  });

  group('Office Knowledge Article', () {
    testWidgets('renders scoped office articles', (tester) async {
      await pumpPage(tester, user: _officeUser(), articles: officeArticles());

      expect(find.text('KNOWLEDGE BASE'), findsOneWidget);
      expect(find.text('OSA student activity clearance'), findsOneWidget);
      expect(find.text('OSA draft handbook note'), findsOneWidget);
      expect(find.text('Office of the Registrar'), findsNothing);
      expect(find.text('Total Articles'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      expect(find.text('1'), findsWidgets);
      expect(find.text('Categories'), findsOneWidget);
    });

    testWidgets('does not show All Offices or Delete', (tester) async {
      await pumpPage(tester, user: _officeUser(), articles: officeArticles());

      expect(find.text('All Offices'), findsNothing);
      expect(find.byKey(const Key('knowledge-article-office-filter')), findsNothing);
      expect(find.text('Delete'), findsNothing);
      expect(find.text('Edit'), findsWidgets);
      expect(find.text('Create Article'), findsOneWidget);
    });

    testWidgets('office search and filters work', (tester) async {
      await pumpPage(tester, user: _officeUser(), articles: officeArticles());

      await tester.enterText(
        find.byKey(const Key('knowledge-article-search')),
        'draft handbook',
      );
      await tester.tap(find.byKey(const Key('knowledge-article-search-btn')));
      await tester.pump();
      expect(find.text('OSA draft handbook note'), findsOneWidget);
      expect(find.text('OSA student activity clearance'), findsNothing);

      await tester.tap(find.byKey(const Key('knowledge-article-reset')));
      await tester.pump();

      await tester.tap(find.byKey(const Key('knowledge-article-status-filter')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Published').last);
      await tester.pumpAndSettle();
      expect(find.text('OSA student activity clearance'), findsOneWidget);
      expect(find.text('OSA draft handbook note'), findsNothing);
    });

    testWidgets('Create Article opens the full create page', (tester) async {
      await pumpPage(tester, user: _officeUser(), articles: officeArticles());

      await tester.tap(find.byKey(const Key('knowledge-article-create')));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.byType(KnowledgeArticleCreatePage), findsOneWidget);
      expect(find.text('Create Knowledge Article'), findsOneWidget);
      expect(find.text('Create draft'), findsNothing);
      expect(find.text('Office workspace'), findsWidgets);
    });

    testWidgets('narrow office layout has no overflow', (tester) async {
      await pumpPage(
        tester,
        user: _officeUser(),
        articles: officeArticles(),
        size: const Size(400, 900),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('OSA student activity clearance'), findsOneWidget);
      expect(find.text('Delete'), findsNothing);
    });
  });

  group('regression', () {
    testWidgets('Knowledge Base extraction copy is unchanged', (tester) async {
      expect(find.text('Extract & Index'), findsNothing);
    });

    testWidgets('Office Dashboard remains unchanged', (tester) async {
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
            home: OfficeDashboardPage(
              debugTickets: const [],
              debugNow: DateTime(2026, 9, 15, 8, 47),
            ),
          ),
        ),
      );
      await tester.pump();
      expect(find.text('WELCOME BACK'), findsOneWidget);
      expect(find.text('Office Dashboard'), findsWidgets);
      expect(find.text('KNOWLEDGE BASE'), findsNothing);
    });

    testWidgets('Assigned Tickets remains inline', (tester) async {
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
                {
                  'ticket_id': 'TK-1',
                  'id': 'TK-1',
                  'user_id': 'u1',
                  'user_name': 'Ana',
                  'user_email': 'ana@example.edu',
                  'original_question': 'Need a Good Moral Certificate',
                  'description': 'Need a Good Moral Certificate',
                  'status': 'Open',
                  'priority': 'Medium',
                  'category': 'Student Records',
                  'assigned_office': 'Office of Student Affairs',
                  'created_at': '2026-09-01T08:00:00Z',
                  'updated_at': '2026-09-01T08:00:00Z',
                  'messages': const <Map<String, dynamic>>[],
                },
              ],
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 80));
      await tester.tap(find.text('Need a Good Moral Certificate'));
      await tester.pump();
      expect(find.byType(Dialog), findsNothing);
      expect(find.byType(AlertDialog), findsNothing);
    });

    testWidgets('Account page remains unaffected', (tester) async {
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
          child: const MaterialApp(
            home: OfficeFacultyAccountsPage(debugUsers: []),
          ),
        ),
      );
      await tester.pump();
      expect(find.text('USER ACCOUNTS'), findsOneWidget);
      expect(find.text('Create Article'), findsNothing);
    });

    testWidgets('Admin Dashboard title remains unchanged', (tester) async {
      await tester.binding.setSurfaceSize(const Size(1400, 1000));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final controller = AuthController(service: _FakeAuthService(_adminUser()));
      await controller.login(const LoginRequest(
        email: 'admin@example.edu',
        password: 'password',
      ));
      await tester.pumpWidget(
        AuthScope(
          controller: controller,
          child: const MaterialApp(home: AdminDashboardPage()),
        ),
      );
      await tester.pump();
      expect(find.text('Admin Dashboard'), findsWidgets);
      expect(find.text('Create Article'), findsNothing);
    });
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
    fullName: 'OSA',
    role: 'office',
    officeId: 'office-1',
    officeName: 'Office of Student Affairs',
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
