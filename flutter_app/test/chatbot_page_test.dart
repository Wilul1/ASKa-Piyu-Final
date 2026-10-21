// Regression tests for the ASKa-Piyu chatbot answer layout after removing
// the yellow "From LSPU source" preview card that used to render above the
// generated answer (it showed the *first* retrieved chunk regardless of
// whether that chunk actually supported the answer — see the citation
// grounding fix in backend/app/services/qa/question_answering.py). The
// expandable Sources section below the answer, confidence indicator, and
// citation/PDF-link metadata must all keep working.
//
// These tests seed a chat session directly into local storage (the same
// JSON shape `_ChatSession`/`_QaAnswer`/`_QaSource` already persist/parse in
// production) so the widget tree can be exercised without a live backend.

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/chatbot_page.dart';
import 'package:aska_piyu/screens/knowledge_base_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/services/local_store.dart';

const _sessionsKey = 'aska_chat_sessions_v1';
// The removed card's exact background color (0xFFFFFBEB / amber-50) and
// badge color (0xFFFEF3C7) — asserting these are gone anywhere on the page
// guards against the card chrome resurfacing under a different label.
const _cardBackground = Color(0xFFFFFBEB);
const _cardBadgeBackground = Color(0xFFFEF3C7);

Map<String, dynamic> _sourceJson({
  required String title,
  required String path,
  int? page,
  String? sourceViewUrl,
  bool pdfAvailable = true,
  String? kbArticleId,
}) {
  return {
    'title': title,
    'path': path,
    'page': page,
    'page_number': page,
    'source_section': path,
    'source_excerpt': 'Sample supporting excerpt for $title.',
    'source_view_url': sourceViewUrl,
    'source_page_url': sourceViewUrl,
    'document_id': 'doc-${title.hashCode}',
    'pdf_available': pdfAvailable,
    'citation_id': 'cit-${title.hashCode}',
    'kb_article_id': kbArticleId,
  };
}

Map<String, dynamic> _seedSessionJson({
  required String question,
  required String answerText,
  required String confidence,
  required List<Map<String, dynamic>> sources,
}) {
  return {
    'id': 'chat_test_1',
    'title': question,
    'updated_at': DateTime(2026, 9, 17).toIso8601String(),
    'turns': [
      {'type': 'user', 'question': question},
      {
        'type': 'answer',
        'answer': {
          'question': question,
          'text': answerText,
          'confidence': confidence,
          'degraded': false,
          'sources': sources,
        },
      },
    ],
  };
}

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

Future<void> _pumpChatbotWithSeededAnswer(
  WidgetTester tester, {
  required String question,
  required String answerText,
  required String confidence,
  required List<Map<String, dynamic>> sources,
  Size size = const Size(1200, 900),
}) async {
  LocalStore.resetForTest();
  SharedPreferences.setMockInitialValues({
    _sessionsKey: jsonEncode([
      _seedSessionJson(
        question: question,
        answerText: answerText,
        confidence: confidence,
        sources: sources,
      ),
    ]),
  });

  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.binding.setSurfaceSize(size);
  addTearDown(() => tester.binding.setSurfaceSize(null));

  final controller = AuthController(service: _FakeAuthService(_studentUser()));
  await controller.login(
    const LoginRequest(email: 'student@example.edu', password: 'password'),
  );

  await tester.pumpWidget(
    AuthScope(
      controller: controller,
      child: const MaterialApp(home: ChatbotPage()),
    ),
  );
  // Hydration runs on a post-frame callback and reads local storage async.
  // The page always opens a new empty chat; the seeded transcript lives in
  // history and must be selected before answer/source assertions.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
  await tester.pump(const Duration(milliseconds: 50));

  final historyTitle = find.text(question);
  expect(historyTitle, findsWidgets);
  await tester.ensureVisible(historyTitle.first);
  await tester.tap(historyTitle.first);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Chatbot answer bubble — yellow source-preview card removed', () {
    testWidgets('old "From LSPU source" preview text no longer renders',
        (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question:
            "I'm transferring to LSPU with a previous degree. How much of "
            'my previous coursework can be credited without validation?',
        answerText:
            'Holders of a degree who transfer or register in LSPU may '
            'receive credit for equivalent courses without validation, but '
            'the credits cannot exceed 50 percent of the total credits '
            'required for graduation.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'Validation Requirements',
            path: 'Student Handbook > Admission > Validation Requirements',
            page: 46,
            sourceViewUrl: '/documents/doc-1/source',
          ),
        ],
      );

      expect(find.text('From LSPU source'), findsNothing);
    });

    testWidgets('old preview card chrome (amber badge/background) is gone',
        (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'How do I validate my ID?',
        answerText: 'Present your Certificate of Registration at the OSAS '
            'window to have your student ID validated.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'ID Validation',
            path: "Citizen's Charter > Student Services > ID Validation",
            page: 18,
            sourceViewUrl: '/documents/doc-9/source',
          ),
        ],
      );

      bool matchesRemovedCardChrome(Widget widget) {
        if (widget is! Container) return false;
        final decoration = widget.decoration;
        if (decoration is! BoxDecoration) return false;
        return decoration.color == _cardBackground ||
            decoration.color == _cardBadgeBackground;
      }

      expect(find.byWidgetPredicate(matchesRemovedCardChrome), findsNothing);
    });

    testWidgets('generated answer still renders', (tester) async {
      const answerText =
          'Holders of a degree may receive credit for equivalent courses '
          'without validation, up to 50% of total credits required for '
          'graduation.';
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'How much credit can be given without validation?',
        answerText: answerText,
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'Validation Requirements',
            path: 'Student Handbook > Validation Requirements',
            page: 46,
          ),
        ],
      );

      expect(
        find.textContaining('Holders of a degree may receive credit'),
        findsOneWidget,
      );
    });

    testWidgets(
        'confidence indicator (Low/Medium/High badge) is no longer rendered '
        '-- removed for the 2026-10-20 UI cleanup; backend confidence is '
        'unaffected, only this visible badge is gone', (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What is the passing grade?',
        answerText: 'A grade of 3.00 or above is passing.',
        confidence: 'medium',
        sources: [
          _sourceJson(
            title: 'Grading System',
            path: 'Student Handbook > Grading System',
            page: 41,
          ),
        ],
      );

      expect(find.text('medium'), findsNothing);
    });

    testWidgets(
        'Sources section still renders below the answer with correct count',
        (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What are the grade ranges for latin honors?',
        answerText: 'Summa cum laude requires 1.20-1.45; magna cum laude '
            '1.46-1.75; cum laude 1.76-2.00.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'Latin Honors',
            path: 'Student Handbook > Graduation > Latin Honors',
            page: 88,
            sourceViewUrl: '/documents/doc-2/source',
          ),
          _sourceJson(
            title: 'Graduation Requirements',
            path: 'Student Handbook > Graduation > Graduation Requirements',
            page: 87,
            sourceViewUrl: '/documents/doc-3/source',
          ),
        ],
      );

      expect(find.text('Sources (2)'), findsOneWidget);
    });

    testWidgets('source metadata and PDF-link affordance remain available',
        (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What are the grade ranges for latin honors?',
        answerText: 'Summa cum laude requires 1.20-1.45; magna cum laude '
            '1.46-1.75; cum laude 1.76-2.00.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'Latin Honors',
            path: 'Student Handbook > Graduation > Latin Honors',
            page: 88,
            sourceViewUrl: '/documents/doc-2/source',
          ),
          _sourceJson(
            title: 'Graduation Requirements',
            path: 'Student Handbook > Graduation > Graduation Requirements',
            page: 87,
            sourceViewUrl: '/documents/doc-3/source',
          ),
        ],
      );

      // Sources start collapsed; expand to inspect each row's metadata.
      await tester.tap(find.text('Sources (2)'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.textContaining('Latin Honors'), findsWidgets);
      expect(find.textContaining('Graduation Requirements'), findsWidgets);
      // Both seeded sources have a source_view_url + document_id, so both
      // rows must remain tappable (no instructional hint text is shown
      // anymore -- see the 2026-10-07 cosmetic cleanup -- but the PDF icon
      // and a real onTap handler must still be present on each row).
      expect(find.byIcon(Icons.picture_as_pdf_outlined), findsNWidgets(2));
      for (final label in ['Latin Honors', 'Graduation Requirements']) {
        final rowInkWell = find.ancestor(
          of: find.textContaining(label).first,
          matching: find.byType(InkWell),
        );
        expect(rowInkWell, findsWidgets);
        expect(tester.widget<InkWell>(rowInkWell.first).onTap, isNotNull);
      }
    });

    testWidgets('layout order is header, answer, then Sources — no card in between',
        (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What is the attendance policy?',
        answerText: 'Students must submit an excuse slip for any absence.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'Attendance Policy',
            path: 'Student Handbook > Attendance Policy',
            page: 12,
          ),
        ],
      );

      final headerFinder = find.text('ASKa-Piyu');
      final answerFinder =
          find.textContaining('Students must submit an excuse slip');
      final sourcesFinder = find.text('Sources (1)');
      expect(headerFinder, findsWidgets);
      expect(answerFinder, findsOneWidget);
      expect(sourcesFinder, findsOneWidget);

      final headerY = tester.getTopLeft(headerFinder.first).dy;
      final answerY = tester.getTopLeft(answerFinder).dy;
      final sourcesY = tester.getTopLeft(sourcesFinder).dy;
      expect(headerY, lessThan(answerY));
      expect(answerY, lessThan(sourcesY));
    });

    testWidgets(
        'a low-confidence answer with zero sources renders no Sources '
        'section and no confidence badge, but the answer text is '
        'preserved as-is', (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What is the deadline for filing an appeal?',
        answerText: 'I do not have enough information in the knowledge base '
            'to answer that question. Please contact the relevant office.',
        confidence: 'low',
        sources: const [],
      );

      expect(find.text('From LSPU source'), findsNothing);
      expect(find.textContaining('Sources ('), findsNothing);
      expect(
        find.textContaining('I do not have enough information'),
        findsOneWidget,
      );
      // Confidence badge removed for the UI cleanup -- the literal word
      // "low" must not appear anywhere as a standalone badge label.
      expect(find.text('low'), findsNothing);
    });

    testWidgets(
        'the two citation-verification warning notices never render, even '
        'for a zero-source answer where the old note would have shown',
        (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What is the deadline for filing an appeal?',
        answerText: 'I do not have enough information in the knowledge base '
            'to answer that question. Please contact the relevant office.',
        confidence: 'low',
        sources: const [],
      );

      expect(
        find.textContaining("No official source was found to support"),
        findsNothing,
      );
      expect(
        find.textContaining('Source verification could not be completed'),
        findsNothing,
      );
      expect(find.byIcon(Icons.error_outline), findsNothing);
    });
  });

  group('Chatbot citation -> public Knowledge Base article link', () {
    testWidgets(
        'a citation with kb_article_id opens the Knowledge Base article, '
        'not the PDF viewer', (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'How do I validate my ID?',
        answerText: 'Present your school ID at the registrar\'s window.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'ID Validation FAQ',
            path: 'Knowledge Base > ID Validation FAQ',
            kbArticleId: 'article-abc-123',
            // Deliberately also has PDF fields -- the article link must
            // still win when both are present.
            sourceViewUrl: '/documents/doc-1/source',
          ),
        ],
      );

      await tester.tap(find.text('Sources (1)'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.byType(KnowledgeBasePage), findsNothing);
      await tester.tap(find.textContaining('ID Validation FAQ').first);
      await tester.pumpAndSettle();

      expect(find.byType(KnowledgeBasePage), findsOneWidget);
    });

    testWidgets(
        'a citation without kb_article_id still falls back to the PDF '
        'viewer, unchanged', (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What are the grade ranges for latin honors?',
        answerText: 'Summa cum laude requires 1.20-1.45.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'Latin Honors',
            path: 'Student Handbook > Graduation > Latin Honors',
            page: 88,
            sourceViewUrl: '/documents/doc-2/source',
          ),
        ],
      );

      await tester.tap(find.text('Sources (1)'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      await tester.tap(find.textContaining('Latin Honors').first);
      await tester.pumpAndSettle();

      // showSourcePdfViewer's own fetch has no backend to reach in this
      // sandbox, so it fails gracefully with its own existing snackbar
      // (a deterministic proof the PDF path -- never the Knowledge Base
      // page -- was the one taken) rather than opening a real dialog.
      expect(find.byType(KnowledgeBasePage), findsNothing);
      expect(
        find.text(
          'PDF source unavailable. Re-index this document to enable PDF viewing.',
        ),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        'a citation with neither kb_article_id nor a PDF source is not '
        'tappable, and opens nothing', (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'How do I validate my ID?',
        answerText: 'Present your school ID at the registrar\'s window.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'ID Validation FAQ',
            path: 'Knowledge Base > ID Validation FAQ',
            sourceViewUrl: null,
            pdfAvailable: false,
          ),
        ],
      );

      await tester.tap(find.text('Sources (1)'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      final rowInkWell = find.ancestor(
        of: find.textContaining('ID Validation FAQ').first,
        matching: find.byType(InkWell),
      );
      expect(tester.widget<InkWell>(rowInkWell.first).onTap, isNull);
    });
  });

  group('Chatbot answer text is selectable (SelectionArea)', () {
    testWidgets('generated answer text is wrapped in a SelectionArea',
        (tester) async {
      const answerText = 'Present your Certificate of Registration at the '
          'OSAS window to have your student ID validated.';
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'How do I validate my ID?',
        answerText: answerText,
        confidence: 'high',
        sources: const [],
      );

      final answerTextFinder =
          find.textContaining('Present your Certificate of Registration');
      expect(answerTextFinder, findsOneWidget);
      expect(
        find.ancestor(
          of: answerTextFinder,
          matching: find.byType(SelectionArea),
        ),
        findsOneWidget,
        reason: 'the generated answer must be wrapped in a SelectionArea so '
            'it can be drag-selected and copied',
      );
    });

    testWidgets(
        'bullet and multi-paragraph formatting is preserved inside the '
        'selectable area',
        (tester) async {
      const answerText = 'Here is how enrollment works:\n\n'
          '- Submit the enrolment slip from the Admission Office.\n'
          '- Present your Certificate of Good Moral Character.\n\n'
          'Processing normally takes a few minutes.';
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'How do I enroll?',
        answerText: answerText,
        confidence: 'high',
        sources: const [],
      );

      // Bullet markers render as literal "•" text (see _ChatMarkdown) --
      // both bullets must still be present, and the whole block must still
      // sit inside the same SelectionArea as the rest of the answer.
      expect(find.text('•  '), findsNWidgets(2));
      expect(
        find.textContaining('Submit the enrolment slip'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Processing normally takes a few minutes'),
        findsOneWidget,
      );
      expect(
        find.ancestor(
          of: find.text('•  ').first,
          matching: find.byType(SelectionArea),
        ),
        findsOneWidget,
      );
    });

    testWidgets(
        'source link remains tappable after the answer becomes selectable',
        (tester) async {
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What are the grade ranges for latin honors?',
        answerText: 'Summa cum laude requires 1.20-1.45; magna cum laude '
            '1.46-1.75; cum laude 1.76-2.00.',
        confidence: 'high',
        sources: [
          _sourceJson(
            title: 'Latin Honors',
            path: 'Student Handbook > Graduation > Latin Honors',
            page: 88,
            sourceViewUrl: '/documents/doc-2/source',
          ),
        ],
      );

      await tester.tap(find.text('Sources (1)'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      final rowInkWell = find.ancestor(
        of: find.textContaining('Latin Honors').first,
        matching: find.byType(InkWell),
      );
      expect(rowInkWell, findsWidgets);
      expect(tester.widget<InkWell>(rowInkWell.first).onTap, isNotNull);

      // The source row must stay OUTSIDE the answer's SelectionArea --
      // its own tap-to-open behavior must not be affected by selection.
      expect(
        find.ancestor(
          of: find.textContaining('Latin Honors').first,
          matching: find.byType(SelectionArea),
        ),
        findsNothing,
      );
    });

    testWidgets('the chat transcript still scrolls with the answer selectable',
        (tester) async {
      // A deliberately long, repeated-bullet answer so the transcript
      // overflows the default viewport and genuinely needs to scroll --
      // the default harness size (1200x900, used by every other test in
      // this file) may also render a desktop history sidebar with its own
      // ListView, so the transcript's ListView is located by ancestry from
      // the answer text itself rather than by widget-type order.
      final longAnswer = List.generate(
        40,
        (i) => '- Requirement $i: submit the corresponding document.',
      ).join('\n');
      await _pumpChatbotWithSeededAnswer(
        tester,
        question: 'What documents are required?',
        answerText: longAnswer,
        confidence: 'high',
        sources: const [],
      );

      final listViewFinder = find.ancestor(
        of: find.textContaining('Requirement 0').first,
        matching: find.byType(ListView),
      );
      expect(listViewFinder, findsOneWidget);
      final controllerBefore =
          tester.widget<ListView>(listViewFinder).controller!;
      expect(controllerBefore.offset, 0);

      await tester.drag(listViewFinder, const Offset(0, -300));
      await tester.pump();

      final controllerAfter =
          tester.widget<ListView>(listViewFinder).controller!;
      expect(controllerAfter.offset, greaterThan(0));
    });
  });
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
