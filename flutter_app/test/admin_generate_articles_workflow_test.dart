import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_quill/flutter_quill.dart';
import 'package:flutter_quill/translations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/admin_article_models.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_generate_articles_page.dart';
import 'package:aska_piyu/screens/knowledge_article_edit_page.dart';
import 'package:aska_piyu/services/admin_article_service.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/services/kb_workspace_session.dart';
import 'package:aska_piyu/widgets/admin_kb_article_shared.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  CandidateSummary candidate({
    required String id,
    required String title,
    required String bucket,
    String category = 'Student Services',
    String office = 'Office of the Registrar',
    String source = 'handbook.pdf',
    String sourceSection = 'Attendance > Excuse Slip',
    bool publishAllowed = true,
    bool saveDraftAllowed = true,
    bool needsReview = false,
    String contentBody = 'Students may request an excuse slip.',
  }) {
    final metadata = {
      'kb_origin': 'document',
      'planner_bucket': bucket,
      'final_bucket': bucket,
      'source_section': sourceSection,
      'source_filename': source,
      'document_type': 'handbook_policy',
      'page_start': 12,
      'page_end': 13,
    };
    return CandidateSummary(
      id: id,
      title: title,
      category: category,
      office: office,
      sourceFilename: source,
      sourceSection: sourceSection,
      plannerBucket: bucket,
      finalBucket: bucket,
      publishAllowed: publishAllowed,
      saveDraftAllowed: saveDraftAllowed,
      needsReview: needsReview,
      isPreview: true,
      summary: contentBody,
      content:
          '$contentBody\n\n----EXTRACTED METADATA----\n${jsonEncode(metadata)}',
    );
  }

  CandidateGenerationResult sampleGeneration() {
    final recommended = candidate(
      id: 'preview-rec-1',
      title: 'Excuse Slip',
      bucket: 'recommended',
    );
    final needsReview = candidate(
      id: 'preview-nr-1',
      title: 'Scholarship Interview',
      bucket: 'needs_review',
      publishAllowed: false,
      needsReview: true,
    );
    final lowQuality = candidate(
      id: 'preview-lq-1',
      title: 'Routine Medical',
      bucket: 'low_quality',
      publishAllowed: false,
    );
    final ragOnly = candidate(
      id: 'preview-rag-1',
      title: 'Internal routing note',
      bucket: 'rag_only',
      publishAllowed: false,
      saveDraftAllowed: false,
    );
    return CandidateGenerationResult(
      totalDetected: 4,
      recommendedCount: 1,
      overflowCount: 0,
      skippedLowQualityCount: 1,
      skippedDuplicateCount: 0,
      needsReviewCount: 1,
      createdCount: 0,
      previewCount: 4,
      blueprintCount: 4,
      ragOnlyCount: 1,
      recommendedCandidates: [recommended],
      needsReviewCandidates: [needsReview],
      lowConfidenceCandidates: [lowQuality],
      allCandidates: [recommended, needsReview, lowQuality, ragOnly],
    );
  }

  Future<void> pumpGenerate(
    WidgetTester tester, {
    required AuthUser user,
    required _FakeArticleService service,
    CandidateGenerationResult? generation,
    Size size = const Size(1400, 1600),
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
          home: Scaffold(
            body: SingleChildScrollView(
              child: AdminGenerateArticlesPage(
                embedded: true,
                debugGenerationResult: generation ?? sampleGeneration(),
                debugArticleService: service,
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  test('Generate Articles remains inside Knowledge Base', () {
    final panel = File('lib/screens/admin_panel_page.dart').readAsStringSync();
    final review =
        File('lib/screens/admin_kb_review_publish_section.dart').readAsStringSync();
    expect(panel, contains('KbReviewAndPublishSection'));
    expect(review, contains('AdminGenerateArticlesPage('));
    expect(review, contains('embedded: true'));
    expect(panel.contains('AdminGenerateArticlesPage('), isFalse);
  });

  test('No Generate Articles sidebar item appears', () {
    final sidebar = File('lib/widgets/sidebar.dart').readAsStringSync();
    expect(sidebar.contains("_SidebarData('Generate Articles'"), isFalse);
    expect(sidebar, contains('adminKnowledgeBase'));
    expect(sidebar, contains('adminKnowledgeArticles'));
    expect(sidebar, contains('officeKnowledgeBase'));
    expect(sidebar, contains('officeKnowledgeArticles'));
  });

  test('Misleading LLM structuring copy is remapped', () {
    expect(sanitizePipelineStageLabel('LLM structuring'),
        'Structuring extracted content');
    expect(
      sanitizePipelineStageLabel('Running LLM structuring now'),
      'Structuring extracted content',
    );
    final workspace =
        File('lib/screens/admin_kb_workspace.dart').readAsStringSync();
    final session =
        File('lib/services/kb_workspace_session.dart').readAsStringSync();
    expect(workspace.contains('LLM structuring'), isFalse);
    expect(session.contains("'LLM structuring'"), isFalse);
    expect(workspace, contains('Structuring extracted content'));
  });

  test('Candidate generation still uses the existing preview API', () {
    final service =
        File('lib/services/admin_article_service.dart').readAsStringSync();
    final page =
        File('lib/screens/admin_generate_articles_page.dart').readAsStringSync();
    expect(service, contains("/admin/kb/articles/generate-preview"));
    expect(page, contains('generateFromPreview('));
    expect(page.contains('generateFromSource('), isFalse);
  });

  test('Second Article Library is gone from Generate Articles', () {
    final page =
        File('lib/screens/admin_generate_articles_page.dart').readAsStringSync();
    final shared =
        File('lib/widgets/admin_kb_article_shared.dart').readAsStringSync();
    expect(page.contains('AdminKbArticleLibrarySection'), isFalse);
    expect(page, contains('View Knowledge Articles'));
    expect(page, contains('KnowledgeArticlesPage('));
    expect(shared, contains('_reviewInWorkspace'));
    expect(shared, contains('KnowledgeArticleEditPage('));
    expect(shared.contains('showAdminArticleEditDialog('), isTrue);
  });

  test('Legacy generate enums remain as Knowledge Base tab deep-links only', () {
    final sidebar = File('lib/widgets/sidebar.dart').readAsStringSync();
    expect(sidebar, contains('adminGenerateArticles'));
    expect(sidebar, contains('officeGenerateArticles'));
    expect(sidebar, contains('initialTab: item == StudentNavItem.adminGenerateArticles ? 1 : 0'));
    expect(sidebar, contains('initialTab: item == StudentNavItem.officeGenerateArticles ? 1 : 0'));
    final panel = File('lib/screens/admin_panel_page.dart').readAsStringSync();
    expect(panel.contains('_GenerateArticlesLinkPanel'), isFalse);
  });

  test('Candidate provenance survives create payload handoff', () {
    final preview = candidate(
      id: 'preview-rec-1',
      title: 'Excuse Slip',
      bucket: 'recommended',
    ).toPreviewArticle();
    expect(preview.contentFormat, 'plain');
    expect(preview.metadata['kb_origin'], 'document');
    expect(preview.metadata['planner_bucket'], 'recommended');
    expect(preview.sourceFilename, 'handbook.pdf');
    expect(preview.office, 'Office of the Registrar');

    final payload = preview.toCreatePayload(publish: false);
    expect(payload['publish_status'], isFalse);
    expect(payload['content_format'], 'plain');
    expect(payload['title'], 'Excuse Slip');
    expect(payload['source_document'], 'handbook.pdf');
    expect(payload['planner_bucket'], 'recommended');
    expect(payload['content'], contains('----EXTRACTED METADATA----'));
    expect(payload['content'], contains('kb_origin'));
    expect(payload['content'], contains('document'));
  });

  test('friendlyKbError hides stack-like details', () {
    expect(
      friendlyKbError(StateError('socket failed host lookup')),
      'Network connection dropped. Check your connection and try again.',
    );
    expect(
      friendlyKbError(AdminArticleRequestException(
        message: 'A similar article already exists.',
        statusCode: 409,
        conflictDetail: const {
          'code': 'similar_article_exists',
          'message': 'A similar article already exists.',
        },
      )),
      'A similar article already exists.',
    );
  });

  testWidgets('admin generate flow renders bucket restrictions', (tester) async {
    final service = _FakeArticleService();
    await pumpGenerate(tester, user: _adminUser(), service: service);

    expect(find.byKey(const Key('admin-generate-articles')), findsOneWidget);
    expect(find.text('Generate Article Candidates'), findsOneWidget);
    expect(find.text('View Knowledge Articles'), findsOneWidget);
    expect(find.text('Excuse Slip'), findsOneWidget);
    expect(find.text('Scholarship Interview'), findsOneWidget);
    expect(find.text('Routine Medical'), findsOneWidget);
    expect(find.text('Recommended Articles (1)'), findsOneWidget);
    expect(find.text('Needs Review (1)'), findsOneWidget);
    expect(find.text('Low Quality / Cleanup (1)'), findsOneWidget);
    expect(find.text('RAG-only (1)'), findsOneWidget);
    expect(find.text('Unsaved Preview'), findsWidgets);
    expect(find.text('Office: Office of the Registrar'), findsWidgets);
    expect(find.text('Source: handbook.pdf'), findsWidgets);

    await tester.ensureVisible(find.text('RAG-only (1)'));
    await tester.tap(find.text('RAG-only (1)'));
    await tester.pumpAndSettle();
    expect(find.text('Internal routing note'), findsOneWidget);

    expect(find.byKey(const Key('candidate-review-preview-rec-1')), findsOneWidget);
    expect(find.byKey(const Key('candidate-review-preview-nr-1')), findsOneWidget);
    expect(find.byKey(const Key('candidate-review-preview-lq-1')), findsOneWidget);
    expect(find.text('Edit as Review Draft'), findsOneWidget);
    expect(find.text('Not recommended for direct publishing'), findsWidgets);
    expect(find.text('Review before publishing'), findsOneWidget);

    final ragCard = find.ancestor(
      of: find.text('Internal routing note'),
      matching: find.byWidgetPredicate(
        (widget) => widget is Padding && widget.padding == const EdgeInsets.only(bottom: 12),
      ),
    );
    expect(
      find.descendant(of: ragCard, matching: find.text('Publish')),
      findsNothing,
    );
    expect(
      find.descendant(of: ragCard, matching: find.text('Save Draft')),
      findsNothing,
    );
    expect(
      find.descendant(
        of: find.ancestor(
          of: find.text('Routine Medical'),
          matching: find.byWidgetPredicate(
            (widget) =>
                widget is Padding &&
                widget.padding == const EdgeInsets.only(bottom: 12),
          ),
        ),
        matching: find.text('Publish'),
      ),
      findsNothing,
    );
  });

  testWidgets('Review of unsaved candidate saves a draft then opens edit workspace',
      (tester) async {
    final service = _FakeArticleService();
    await pumpGenerate(tester, user: _adminUser(), service: service);

    await tester.ensureVisible(find.byKey(const Key('candidate-review-preview-rec-1')));
    await tester.tap(find.byKey(const Key('candidate-review-preview-rec-1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pumpAndSettle();

    expect(service.createCalls, 1);
    expect(service.lastCreatePayload?['publish_status'], isFalse);
    expect(service.lastCreatePayload?['title'], 'Excuse Slip');
    expect(service.lastCreatePayload?['content_format'], 'plain');
    expect(service.lastCreatePayload?['content'], contains('EXTRACTED METADATA'));
    expect(find.byType(KnowledgeArticleEditPage), findsOneWidget);
    expect(find.text('Edit Article'), findsWidgets);
    expect(find.text('Excuse Slip'), findsWidgets);
  });

  testWidgets('office generate flow stays on the same workspace and save API',
      (tester) async {
    final service = _FakeArticleService();
    await pumpGenerate(tester, user: _officeUser(), service: service);

    expect(find.byKey(const Key('admin-generate-articles')), findsOneWidget);
    expect(find.text('Excuse Slip'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('candidate-review-preview-rec-1')));
    await tester.tap(find.byKey(const Key('candidate-review-preview-rec-1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pumpAndSettle();

    expect(service.createCalls, 1);
    expect(service.lastCreatePayload?['publish_status'], isFalse);
    expect(find.byType(KnowledgeArticleEditPage), findsOneWidget);
  });

  testWidgets('duplicate candidate save shows similar-article dialog', (tester) async {
    final service = _FakeArticleService()
      ..createError = AdminArticleRequestException(
        message: 'A similar article already exists.',
        statusCode: 409,
        conflictDetail: const {
          'code': 'similar_article_exists',
          'message': 'A similar article already exists.',
          'existing': {'id': 'existing-1', 'title': 'Excuse Slip'},
        },
      );
    await pumpGenerate(tester, user: _adminUser(), service: service);

    await tester.ensureVisible(find.byKey(const Key('candidate-review-preview-rec-1')));
    await tester.tap(find.byKey(const Key('candidate-review-preview-rec-1')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pumpAndSettle();

    expect(find.text('Similar article found'), findsOneWidget);
    expect(find.text('Update Existing'), findsOneWidget);
    expect(find.text('Create New'), findsOneWidget);
    expect(find.byType(KnowledgeArticleEditPage), findsNothing);
  });

  testWidgets('tapping generate uses the existing preview API', (tester) async {
    final service = _FakeArticleService()..generationResult = sampleGeneration();
    await pumpGenerate(tester, user: _adminUser(), service: service);

    await tester.tap(find.text('Generate Article Candidates'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(service.generateCalled, isTrue);
  });

  testWidgets('narrow generate review has no overflow', (tester) async {
    final service = _FakeArticleService();
    await pumpGenerate(
      tester,
      user: _officeUser(),
      service: service,
      size: const Size(390, 900),
    );
    expect(tester.takeException(), isNull);
    expect(find.text('Excuse Slip'), findsOneWidget);
    expect(find.text('View Knowledge Articles'), findsOneWidget);
    await tester.ensureVisible(find.text('Routine Medical'));
    expect(tester.takeException(), isNull);
  });

  test('Existing Knowledge Article create/edit pages remain the workspace', () {
    final articles =
        File('lib/screens/knowledge_articles_page.dart').readAsStringSync();
    final create =
        File('lib/screens/knowledge_article_create_page.dart').readAsStringSync();
    final edit =
        File('lib/screens/knowledge_article_edit_page.dart').readAsStringSync();
    expect(articles, contains('class KnowledgeArticlesPage'));
    expect(create, contains('class KnowledgeArticleCreatePage'));
    expect(edit, contains('class KnowledgeArticleEditPage'));
    expect(edit, contains('this.articleService'));
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

class _FakeArticleService extends AdminArticleService {
  _FakeArticleService() : super(apiBase: 'http://test.local', setAdminHeader: (_) {});

  bool generateCalled = false;
  CandidateGenerationResult? generationResult;
  int createCalls = 0;
  Map<String, dynamic>? lastCreatePayload;
  AdminArticleRequestException? createError;
  final Map<String, AdminArticle> articles = {};

  @override
  Future<CandidateGenerationResult> generateFromPreview({
    required Map<String, dynamic> preview,
    String? filename,
    int? maxCandidates,
    String saveMode = 'preview_only',
  }) async {
    generateCalled = true;
    return generationResult ??
        (throw StateError('missing generation result'));
  }

  @override
  Future<AdminArticle> createArticle(
    Map<String, dynamic> payload, {
    String? updateExistingId,
    bool forceCreate = false,
  }) async {
    createCalls += 1;
    lastCreatePayload = payload;
    if (createError != null && createCalls == 1) {
      throw createError!;
    }
    final id = (updateExistingId != null && updateExistingId.trim().isNotEmpty)
        ? updateExistingId.trim()
        : 'saved-$createCalls';
    final content = payload['content']?.toString() ?? '';
    final article = AdminArticle(
      id: id,
      title: payload['title']?.toString() ?? 'Untitled',
      category: payload['category']?.toString() ?? 'General Information',
      published: payload['publish_status'] == true,
      summary: payload['summary']?.toString(),
      content: content,
      office: payload['office']?.toString(),
      sourceFilename: payload['source_document']?.toString(),
      metadata: {
        if (payload['planner_bucket'] != null)
          'planner_bucket': payload['planner_bucket'],
        if (payload['source_section'] != null)
          'source_section': payload['source_section'],
        'kb_origin': 'document',
      },
      displayContent: content.split('----EXTRACTED METADATA----').first.trim(),
      contentFormat: payload['content_format']?.toString() ?? 'plain',
    );
    articles[id] = article;
    return article;
  }

  @override
  Future<AdminArticle> getArticle(String id) async {
    final article = articles[id];
    if (article == null) {
      throw StateError('missing article $id');
    }
    return article;
  }
}
