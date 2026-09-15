import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_quill/flutter_quill.dart';
import 'package:flutter_quill/translations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/admin_article_models.dart';
import 'package:aska_piyu/models/article_media_models.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/knowledge_article_edit_page.dart';
import 'package:aska_piyu/screens/knowledge_articles_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/services/file_pick.dart';
import 'package:aska_piyu/widgets/article_rich_editor.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  AdminArticle sample({
    String id = 'a1',
    String title = 'How do I get an excuse slip if I missed class because I was sick',
    String category = 'Academic Policies',
    bool published = true,
    String content =
        'A student who missed class for an unavoidable reason must get an excuse slip.',
    String contentFormat = 'plain',
    String office = 'Office of Student Affairs',
    String audience = 'student',
    String? summary =
        'A student who missed class for an unavoidable reason must get an excuse slip from OSAS.',
    String? sourceFilename = 'Student_Handbook_UG_Academic_Policies.pdf',
    String? updatedAt = '2026-09-05T02:24:00Z',
    List<ArticleMediaItem> attachments = const [],
  }) {
    return AdminArticle(
      id: id,
      title: title,
      category: category,
      published: published,
      summary: summary,
      content: content,
      office: office,
      sourceFilename: sourceFilename,
      updatedAt: updatedAt,
      audience: audience,
      displayContent: content,
      contentFormat: contentFormat,
      attachments: attachments,
      media: attachments,
    );
  }

  Future<void> pumpEdit(
    WidgetTester tester, {
    required AuthUser user,
    required AdminArticle article,
    Size size = const Size(1400, 1600),
    List<String> knownOffices = const [
      'Office of Student Affairs',
      'Office of the Registrar',
    ],
    Future<AdminArticle> Function(String id, Map<String, dynamic> payload)?
        debugUpdateArticle,
    Future<void> Function(String id)? debugPublishArticle,
    Future<void> Function(String id)? debugUnpublishArticle,
    Future<ArticleMediaItem> Function({
      required PickedAppFile file,
      required String kind,
    })? debugUploadMedia,
    Future<void> Function(String mediaId)? debugDeleteMedia,
    Future<List<PickedAppFile>> Function()? debugPickFiles,
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
          localizationsDelegates: const [
            FlutterQuillLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          home: home ??
              KnowledgeArticleEditPage(
                articleId: article.id,
                setAdminHeader: (_) {},
                knownCategories: const ['Academic Policies', 'Student Services'],
                knownOffices: knownOffices,
                debugOfficeNames: knownOffices,
                debugGetArticle: (_) async => article,
                debugUpdateArticle: debugUpdateArticle,
                debugPublishArticle: debugPublishArticle,
                debugUnpublishArticle: debugUnpublishArticle,
                debugUploadMedia: debugUploadMedia,
                debugDeleteMedia: debugDeleteMedia ?? (_) async {},
                debugPickFiles: debugPickFiles,
              ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  group('Edit Article page', () {
    testWidgets('admin workspace matches create layout without fake fields',
        (tester) async {
      await pumpEdit(tester, user: _adminUser(), article: sample());

      expect(find.text('Knowledge Base'), findsWidgets);
      expect(find.text('Edit Article'), findsWidgets);
      expect(
        find.text(
          'Update the content and details of this knowledge base article.',
        ),
        findsWidgets,
      );
      expect(find.text('Back to Articles'), findsOneWidget);
      expect(find.text('Article Information'), findsOneWidget);
      expect(find.text('Update the core details of the article.'), findsOneWidget);
      expect(find.text('Title'), findsOneWidget);
      expect(find.text('Category'), findsOneWidget);
      expect(find.text('Audience'), findsOneWidget);
      expect(find.text('Office'), findsOneWidget);
      expect(find.text('Summary'), findsOneWidget);
      expect(find.text('Article Content'), findsOneWidget);
      expect(find.text('Additional Details'), findsOneWidget);
      expect(find.text('Source filename'), findsOneWidget);
      expect(find.text('Publish Settings'), findsOneWidget);
      expect(find.text('Status'), findsOneWidget);
      expect(find.text('Last updated'), findsOneWidget);
      expect(find.text('Published'), findsWidgets);
      expect(find.text('Attachments (optional)'), findsWidgets);
      expect(find.text('Unpublish'), findsOneWidget);
      expect(find.text('Save Changes'), findsOneWidget);
      expect(find.byKey(const Key('article-editor-toolbar')), findsOneWidget);
      expect(find.byKey(const Key('article-editor-bold')), findsOneWidget);
      expect(find.byKey(const Key('article-editor-image')), findsOneWidget);
      expect(find.text('Tags'), findsNothing);
      expect(find.text('Tags (optional)'), findsNothing);
      expect(find.text('0/200'), findsNothing);
      expect(find.text('0/5000'), findsNothing);
      expect(find.text('Submit for review'), findsNothing);
    });

    testWidgets('loads existing plain content without converting it',
        (tester) async {
      const body =
          'A student who missed class for an unavoidable reason must get an excuse slip.';
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(content: body, contentFormat: 'plain'),
      );

      expect(find.textContaining('excuse slip'), findsWidgets);
      final editor = tester.state<ArticleRichEditorState>(
        find.byType(ArticleRichEditor),
      );
      expect(editor.value.contentFormat, 'plain');
      expect(editor.value.content.contains('excuse slip'), isTrue);
    });

    testWidgets('loads existing HTML formatting into the real editor',
        (tester) async {
      const html =
          '<h2>Hours</h2><p>The desk is <strong>open</strong> today.</p>';
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(content: html, contentFormat: 'html', published: false),
      );

      final editor = tester.state<ArticleRichEditorState>(
        find.byType(ArticleRichEditor),
      );
      expect(editor.value.contentFormat, 'html');
      expect(editor.controller.document.toPlainText(), contains('open'));
      expect(find.text('Draft'), findsWidgets);
      expect(find.text('Publish'), findsOneWidget);
      expect(find.text('Unpublish'), findsNothing);
    });

    testWidgets('Save Changes patches content without publish_status',
        (tester) async {
      Map<String, dynamic>? captured;
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(),
        debugUpdateArticle: (id, payload) async {
          captured = payload;
          return sample();
        },
      );

      await tester.enterText(
        find.byKey(const Key('knowledge-article-edit-title')),
        'Updated excuse slip title',
      );
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-edit-save')),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-edit-save')));
      await tester.pumpAndSettle();

      expect(captured, isNotNull);
      expect(captured!['title'], 'Updated excuse slip title');
      expect(captured!.containsKey('publish_status'), isFalse);
      expect(captured!['content_format'], 'plain');
    });

    testWidgets('Unpublish uses the dedicated unpublish action',
        (tester) async {
      var unpublished = false;
      var patched = false;
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(published: true),
        debugUnpublishArticle: (_) async => unpublished = true,
        debugUpdateArticle: (id, payload) async {
          patched = true;
          return sample();
        },
      );

      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-edit-unpublish')),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-edit-unpublish')));
      await tester.pumpAndSettle();
      expect(unpublished, isTrue);
      expect(patched, isFalse);
      expect(find.text('Draft'), findsWidgets);
      expect(find.text('Publish'), findsOneWidget);
    });

    testWidgets('Publish uses the dedicated publish action', (tester) async {
      var published = false;
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(published: false),
        debugPublishArticle: (_) async => published = true,
      );

      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-edit-publish')),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-edit-publish')));
      await tester.pumpAndSettle();
      expect(published, isTrue);
      expect(find.text('Published'), findsWidgets);
      expect(find.text('Unpublish'), findsOneWidget);
    });

    testWidgets('existing attachments can be shown, added, and removed',
        (tester) async {
      final existing = ArticleMediaItem(
        id: 'att-old',
        originalFilename: 'handbook.pdf',
        storedFilename: 'handbook.pdf',
        contentType: 'application/pdf',
        kind: 'attachment',
        sizeBytes: 12,
        url: '/kb/media/handbook.pdf',
      );
      String? deletedId;
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(attachments: [existing]),
        debugUploadMedia: ({required file, required kind}) async {
          return ArticleMediaItem(
            id: 'att-new',
            originalFilename: file.name,
            storedFilename: file.name,
            contentType: 'application/pdf',
            kind: kind,
            sizeBytes: file.bytes.length,
            url: '/kb/media/${file.name}',
          );
        },
        debugDeleteMedia: (id) async => deletedId = id,
        debugPickFiles: () async {
          return [
            PickedAppFile(
              name: 'note.pdf',
              bytes: Uint8List.fromList('%PDF-1.4'.codeUnits),
            ),
          ];
        },
      );

      expect(find.text('handbook.pdf'), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-attachments-dropzone')),
      );
      await tester.tap(
        find.byKey(const Key('knowledge-article-attachments-dropzone')),
      );
      await tester.pumpAndSettle();
      expect(find.text('note.pdf'), findsOneWidget);

      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-attachment-remove-att-old')),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-attachment-remove-att-old')));
      await tester.pumpAndSettle();
      expect(deletedId, 'att-old');
      expect(find.text('handbook.pdf'), findsNothing);
    });

    testWidgets('office office field is locked and save keeps office scope',
        (tester) async {
      Map<String, dynamic>? captured;
      await pumpEdit(
        tester,
        user: _officeUser(),
        article: sample(office: 'Office of Student Affairs'),
        debugUpdateArticle: (id, payload) async {
          captured = payload;
          return sample();
        },
      );

      expect(find.text('Office of Student Affairs'), findsWidgets);
      expect(find.byIcon(Icons.lock_outline), findsWidgets);
      expect(find.text('Delete'), findsNothing);

      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-edit-save')),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-edit-save')));
      await tester.pumpAndSettle();
      expect(captured?['office'], 'Office of Student Affairs');
    });

    testWidgets('Back to Articles returns to the article list', (tester) async {
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(),
        home: KnowledgeArticlesPage(
          debugArticles: [
            {
              'id': 'a1',
              'title': 'How do I get an excuse slip if I missed class?',
              'office': 'Office of Student Affairs',
              'category': 'Academic Policies',
              'published': true,
              'summary': 'excuse slip',
              'content': 'Bring a medical certificate.',
              'updated_at': '2026-09-05T08:00:00Z',
            },
          ],
          debugOfficeNames: const ['Office of Student Affairs'],
        ),
      );
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-edit-a1')),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-edit-a1')));
      await tester.pumpAndSettle();
      expect(find.byType(KnowledgeArticleEditPage), findsOneWidget);
      expect(find.text('Edit Article'), findsWidgets);

      await tester.tap(find.byKey(const Key('knowledge-article-edit-back')));
      await tester.pumpAndSettle();
      expect(find.byType(KnowledgeArticleEditPage), findsNothing);
      expect(find.text('Knowledge Article'), findsWidgets);
    });

    testWidgets('unsaved changes confirm before leaving', (tester) async {
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(),
        home: KnowledgeArticlesPage(
          debugArticles: [
            {
              'id': 'a1',
              'title': 'Excuse slip',
              'office': 'Office of Student Affairs',
              'category': 'Academic Policies',
              'published': true,
              'content': 'Bring a medical certificate.',
              'updated_at': '2026-09-05T08:00:00Z',
            },
          ],
          debugOfficeNames: const ['Office of Student Affairs'],
        ),
      );
      await tester.ensureVisible(
        find.byKey(const Key('knowledge-article-edit-a1')),
      );
      await tester.tap(find.byKey(const Key('knowledge-article-edit-a1')));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.byKey(const Key('knowledge-article-edit-title')),
        'Changed title',
      );
      await tester.tap(find.byKey(const Key('knowledge-article-edit-back')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('knowledge-article-edit-unsaved-dialog')),
          findsOneWidget);
      await tester.tap(find.text('Stay'));
      await tester.pumpAndSettle();
      expect(find.byType(KnowledgeArticleEditPage), findsOneWidget);
    });

    testWidgets('narrow layout has no overflow', (tester) async {
      await pumpEdit(
        tester,
        user: _adminUser(),
        article: sample(),
        size: const Size(390, 1200),
      );
      expect(tester.takeException(), isNull);
      expect(find.byKey(const Key('knowledge-article-edit-page')), findsOneWidget);
      expect(find.text('Article Information'), findsOneWidget);
      expect(find.text('Additional Details'), findsOneWidget);
      expect(find.text('Publish Settings'), findsOneWidget);
      expect(find.text('Save Changes'), findsOneWidget);
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
