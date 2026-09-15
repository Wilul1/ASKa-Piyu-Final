import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/admin_article_models.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/knowledge_article_create_page.dart';
import 'package:aska_piyu/screens/knowledge_articles_page.dart';
import 'package:aska_piyu/services/admin_article_service.dart';
import 'package:aska_piyu/services/auth_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  AdminArticle createdFrom(Map<String, dynamic> payload, {String id = 'new-1'}) {
    return AdminArticle(
      id: id,
      title: payload['title']?.toString() ?? 'Untitled',
      category: payload['category']?.toString() ?? 'General',
      published: payload['publish_status'] == true,
      summary: payload['summary']?.toString(),
      content: payload['content']?.toString(),
      office: payload['office']?.toString(),
    );
  }

  Future<void> pumpCreate(
    WidgetTester tester, {
    required AuthUser user,
    Size size = const Size(1400, 1000),
    List<String> knownCategories = const ['Student Services'],
    List<String> knownOffices = const [
      'Office of Student Affairs',
      'Office of the Registrar',
    ],
    List<String>? debugOfficeNames,
    Future<AdminArticle> Function(Map<String, dynamic> payload)?
        debugCreateArticle,
    Widget? home,
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
          home: home ??
              KnowledgeArticleCreatePage(
                service: AdminArticleService(
                  apiBase: '',
                  setAdminHeader: (_) {},
                ),
                knownCategories: knownCategories,
                knownOffices: knownOffices,
                debugOfficeNames: debugOfficeNames ?? knownOffices,
                debugCreateArticle: debugCreateArticle ??
                    (payload) async => createdFrom(payload),
              ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  Future<void> fillRequired(
    WidgetTester tester, {
    String title = 'Student activity clearance',
    String category = 'Student Services',
    String content = 'Bring your ID to OSA.',
  }) async {
    await tester.enterText(
      find.byKey(const Key('knowledge-article-create-title')),
      title,
    );
    await tester.enterText(
      find.byKey(const Key('knowledge-article-create-category')),
      category,
    );
    await tester.enterText(
      find.byKey(const Key('knowledge-article-create-content')),
      content,
    );
    await tester.pump();
  }

  group('Create Knowledge Article page', () {
    testWidgets('renders basic information, content, and real required fields',
        (tester) async {
      await pumpCreate(tester, user: _adminUser());

      expect(find.text('Knowledge Base'), findsWidgets);
      expect(find.text('Create Knowledge Article'), findsWidgets);
      expect(find.text('Share helpful information with students and staff. Save a draft now, or publish when the article should appear in the Knowledge Base.'),
          findsOneWidget);
      expect(find.text('Basic Information'), findsOneWidget);
      expect(find.text('Provide the essential details about your article.'),
          findsOneWidget);
      expect(find.text('Title'), findsOneWidget);
      expect(find.text('Category'), findsOneWidget);
      expect(find.text('Related Office'), findsOneWidget);
      expect(find.text('Content'), findsOneWidget);
      expect(find.text('Publish Settings'), findsOneWidget);
      expect(find.byKey(const Key('knowledge-article-create-title')),
          findsOneWidget);
      expect(find.byKey(const Key('knowledge-article-create-category')),
          findsOneWidget);
      expect(find.byKey(const Key('knowledge-article-create-content')),
          findsOneWidget);
      expect(find.text('Enter a clear and descriptive title'), findsOneWidget);
      expect(find.text('0/200'), findsNothing);
      expect(find.text('0/5000'), findsNothing);
      expect(find.text('Tags'), findsNothing);
      expect(find.text('Tags (optional)'), findsNothing);
      expect(find.text('Attachments'), findsNothing);
      expect(find.text('Attachments (optional)'), findsNothing);
      expect(find.text('Submit for review'), findsNothing);
      expect(find.text('Submit for Review'), findsNothing);
      expect(find.text('Articles will be reviewed before publishing'),
          findsNothing);
    });

    testWidgets('Back to Articles returns without creating when untouched',
        (tester) async {
      await pumpCreate(
        tester,
        user: _adminUser(),
        home: KnowledgeArticlesPage(
          debugArticles: const [],
          debugCreateArticle: (payload) async => createdFrom(payload),
          debugOfficeNames: const ['Office of the Registrar'],
        ),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-create')));
      await tester.pumpAndSettle();
      expect(find.byType(KnowledgeArticleCreatePage), findsOneWidget);

      await tester.tap(find.byKey(const Key('knowledge-article-create-back')));
      await tester.pumpAndSettle();
      expect(find.byType(KnowledgeArticleCreatePage), findsNothing);
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.text('Knowledge Article'), findsWidgets);
      expect(find.text('Create Article'), findsOneWidget);
    });

    testWidgets('unsaved changes confirm before leaving', (tester) async {
      await pumpCreate(
        tester,
        user: _adminUser(),
        home: KnowledgeArticlesPage(
          debugArticles: const [],
          debugCreateArticle: (payload) async => createdFrom(payload),
          debugOfficeNames: const ['Office of the Registrar'],
        ),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-create')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('knowledge-article-create-title')),
        'Unsaved title',
      );
      await tester.pump();
      await tester.tap(find.byKey(const Key('knowledge-article-create-back')));
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('knowledge-article-create-unsaved-dialog')),
        findsOneWidget,
      );
      await tester.tap(find.text('Stay'));
      await tester.pumpAndSettle();
      expect(find.byType(KnowledgeArticleCreatePage), findsOneWidget);

      await tester.tap(find.byKey(const Key('knowledge-article-create-back')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Leave'));
      await tester.pumpAndSettle();
      expect(find.byType(KnowledgeArticleCreatePage), findsNothing);
      expect(find.text('Create Article'), findsOneWidget);
    });

    testWidgets('validation requires title and category', (tester) async {
      await pumpCreate(tester, user: _adminUser());

      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.tap(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.pump();
      expect(find.text('Enter a title.'), findsOneWidget);
      expect(find.text('Enter a category.'), findsOneWidget);
    });

    testWidgets('draft creation uses the existing create payload',
        (tester) async {
      Map<String, dynamic>? captured;
      await pumpCreate(
        tester,
        user: _adminUser(),
        debugOfficeNames: const [
          'Office of Student Affairs',
          'Office of the Registrar',
        ],
        debugCreateArticle: (payload) async {
          captured = payload;
          return createdFrom(payload);
        },
      );

      await fillRequired(tester);
      await tester.tap(find.byKey(const Key('knowledge-article-create-office')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Office of the Registrar').last);
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.tap(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.pumpAndSettle();

      expect(captured, isNotNull);
      expect(captured!['title'], 'Student activity clearance');
      expect(captured!['category'], 'Student Services');
      expect(captured!['content'], 'Bring your ID to OSA.');
      expect(captured!['publish_status'], isFalse);
      expect(captured!['office'], 'Office of the Registrar');
    });

    testWidgets('loading prevents duplicate submission', (tester) async {
      var calls = 0;
      final gate = Completer<AdminArticle>();
      await pumpCreate(
        tester,
        user: _adminUser(),
        debugCreateArticle: (payload) async {
          calls += 1;
          return gate.future;
        },
      );

      await fillRequired(tester);
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.tap(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.pump();
      await tester.tap(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.pump();
      expect(calls, 1);
      expect(find.byType(CircularProgressIndicator), findsWidgets);

      gate.complete(createdFrom({
        'title': 'Student activity clearance',
        'category': 'Student Services',
        'publish_status': false,
      }));
      await tester.pumpAndSettle();
    });

    testWidgets('errors remain visible after a failed create', (tester) async {
      await pumpCreate(
        tester,
        user: _adminUser(),
        debugCreateArticle: (payload) async {
          throw Exception('Could not create article.');
        },
      );

      await fillRequired(tester);
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.tap(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('knowledge-article-create-error')),
        findsOneWidget,
      );
      expect(find.textContaining('Could not create article.'), findsOneWidget);
      expect(find.byType(KnowledgeArticleCreatePage), findsOneWidget);
    });

    testWidgets('successful draft returns to the article list', (tester) async {
      await pumpCreate(
        tester,
        user: _adminUser(),
        home: KnowledgeArticlesPage(
          debugArticles: const [],
          debugOfficeNames: const ['Office of the Registrar'],
          debugCreateArticle: (payload) async => createdFrom(payload),
        ),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-create')));
      await tester.pumpAndSettle();
      await fillRequired(tester);
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.tap(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.pumpAndSettle();
      expect(find.byType(KnowledgeArticleCreatePage), findsNothing);
      expect(find.text('Create Article'), findsOneWidget);
      expect(
        find.text('Saved draft "Student activity clearance".'),
        findsOneWidget,
      );
    });

    testWidgets('Admin can choose an office from the real office list',
        (tester) async {
      await pumpCreate(
        tester,
        user: _adminUser(),
        debugOfficeNames: const [
          'Office of Student Affairs',
          'Office of the Registrar',
        ],
      );

      expect(find.byType(DropdownButtonFormField<String>), findsWidgets);
      await tester.tap(find.byKey(const Key('knowledge-article-create-office')));
      await tester.pumpAndSettle();
      expect(find.text('Office of the Registrar'), findsWidgets);
      expect(find.text('Office of Student Affairs'), findsWidgets);
    });

    testWidgets('Office actor cannot select another office', (tester) async {
      Map<String, dynamic>? captured;
      await pumpCreate(
        tester,
        user: _officeUser(),
        debugCreateArticle: (payload) async {
          captured = payload;
          return createdFrom(payload);
        },
      );

      expect(find.text('Office of Student Affairs'), findsWidgets);
      expect(find.byIcon(Icons.lock_outline), findsOneWidget);
      await tester.tap(find.byKey(const Key('knowledge-article-create-office')));
      await tester.pumpAndSettle();
      expect(find.text('Office of the Registrar'), findsNothing);

      await fillRequired(tester);
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.tap(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      await tester.pumpAndSettle();
      expect(captured?['office'], 'Office of Student Affairs');
    });

    testWidgets('publishing controls match actual permissions', (tester) async {
      Map<String, dynamic>? captured;
      await pumpCreate(
        tester,
        user: _officeUser(),
        debugCreateArticle: (payload) async {
          captured = payload;
          return createdFrom(payload);
        },
      );

      expect(find.text('Save as draft'), findsOneWidget);
      expect(find.text('Publish Article'), findsOneWidget);
      expect(find.text('Submit for review'), findsNothing);
      await tester.tap(find.byKey(const Key('knowledge-article-create-status')));
      await tester.pumpAndSettle();
      expect(find.text('Draft'), findsWidgets);
      expect(find.text('Published'), findsWidgets);
      await tester.tap(find.text('Published').last);
      await tester.pumpAndSettle();

      await fillRequired(tester);
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-create-publish')),
      );
      await tester.tap(
        find.byKey(const Key('knowledge-article-create-publish')),
      );
      await tester.pumpAndSettle();
      expect(captured?['publish_status'], isTrue);
    });

    testWidgets('narrow layout has no overflow', (tester) async {
      await pumpCreate(
        tester,
        user: _officeUser(),
        size: const Size(400, 900),
      );
      expect(tester.takeException(), isNull);
      expect(find.text('Create Knowledge Article'), findsWidgets);
      expect(find.text('Basic Information'), findsOneWidget);
      expect(find.text('Publish Settings'), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-create-save-draft')),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('Admin and Office scaffolds stay on Knowledge Article',
        (tester) async {
      await pumpCreate(tester, user: _adminUser());
      expect(find.text('Knowledge Article'), findsWidgets);
      expect(find.text('Create Knowledge Article'), findsOneWidget);

      await pumpCreate(tester, user: _officeUser());
      expect(find.text('Office workspace'), findsWidgets);
      expect(find.text('Knowledge Article'), findsWidgets);
      expect(find.text('Assigned Tickets'), findsWidgets);
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
