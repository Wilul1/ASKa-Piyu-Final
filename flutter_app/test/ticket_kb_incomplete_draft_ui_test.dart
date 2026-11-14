import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_quill/flutter_quill.dart';
import 'package:flutter_quill/translations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/admin_article_models.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_management_pages.dart';
import 'package:aska_piyu/screens/knowledge_article_edit_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/services/kb_compose_helpers.dart';
import 'package:aska_piyu/widgets/ticket_kb_incomplete_draft_banner.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('ticket KB completion helpers', () {
    test('detects completion marker and keeps publish unblocked', () {
      expect(
        contentHasTicketKbCompletionMarker(ticketKbCompletionMarker),
        isTrue,
      );
      expect(
        ticketKbIncompleteWarning(
          needsManualCompletion: true,
          content: 'Enough reusable answer text for a draft body.',
        ),
        isTrue,
      );
      expect(
        ticketKbIncompleteWarning(
          needsManualCompletion: false,
          content: 'Answer\n\n$ticketKbCompletionMarker',
        ),
        isTrue,
      );
      expect(
        ticketKbPublishBlocked(
          needsManualCompletion: true,
          content: 'Answer\n\n$ticketKbCompletionMarker',
        ),
        isFalse,
      );
      expect(
        ticketKbPublishBlocked(
          needsManualCompletion: false,
          content: 'Complete reusable Registrar steps for COE requests.',
        ),
        isFalse,
      );
    });

    test('formats known generation_notes codes', () {
      expect(
        formatTicketKbGenerationNotes('incomplete_referral'),
        contains('referred'),
      );
      expect(
        formatTicketKbGenerationNotes('deferred_answer'),
        contains('status update'),
      );
      expect(formatTicketKbGenerationNotes(null), isNull);
      expect(formatTicketKbGenerationNotes('  '), isNull);
    });
  });

  group('TicketKbIncompleteDraftBanner', () {
    testWidgets('shows incomplete warning and readable notes', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: TicketKbIncompleteDraftBanner(
              generationNotes: 'incomplete_referral',
            ),
          ),
        ),
      );

      expect(find.byKey(const Key('ticket-kb-incomplete-banner')), findsOneWidget);
      expect(
        find.text('Needs staff review before publishing'),
        findsOneWidget,
      );
      expect(
        find.textContaining(
          'may not have enough reusable detail',
        ),
        findsOneWidget,
      );
      expect(find.byKey(const Key('ticket-kb-generation-notes')), findsOneWidget);
      expect(find.textContaining('referred the student'), findsOneWidget);
    });

    testWidgets('hides when show is false (ordinary / completed drafts)',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: TicketKbIncompleteDraftBanner(show: false),
          ),
        ),
      );
      expect(find.byKey(const Key('ticket-kb-incomplete-banner')), findsNothing);
    });
  });

  group('KnowledgeArticleEditPage incomplete ticket drafts', () {
    AuthUser admin() => const AuthUser(
          id: 'admin-1',
          email: 'admin@example.com',
          fullName: 'Admin User',
          role: 'admin',
          officeId: null,
          officeName: null,
          emailVerified: true,
          createdAt: null,
          updatedAt: null,
        );

    Future<void> pumpEdit(
      WidgetTester tester, {
      required AdminArticle article,
    }) async {
      await tester.binding.setSurfaceSize(const Size(1400, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final controller = AuthController(service: _FakeAuthService(admin()));
      await controller.login(
        const LoginRequest(email: 'admin@example.com', password: 'password'),
      );

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
            home: KnowledgeArticleEditPage(
              articleId: article.id,
              setAdminHeader: (_) {},
              knownCategories: const ['Student Records'],
              knownOffices: const ['Office of the Registrar'],
              debugGetArticle: (_) async => article,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('incomplete ticket draft shows banner but keeps Publish enabled',
        (tester) async {
      final article = AdminArticle(
        id: 'inc-1',
        title: 'Certificate of Enrollment',
        category: 'Student Records',
        published: false,
        content: 'Partial note.\n\n$ticketKbCompletionMarker',
        displayContent: 'Partial note.\n\n$ticketKbCompletionMarker',
        office: 'Office of the Registrar',
        kbOrigin: 'ticket_resolution',
        sourceTicketId: 'TK-1',
        needsManualCompletion: true,
        generationNotes: 'deferred_answer',
      );

      await pumpEdit(tester, article: article);

      expect(find.byKey(const Key('ticket-kb-incomplete-banner')), findsOneWidget);
      expect(find.textContaining('status update'), findsOneWidget);
      expect(find.textContaining('warning only'), findsOneWidget);

      final publish = tester.widget<OutlinedButton>(
        find.byKey(const Key('knowledge-article-edit-publish')),
      );
      expect(publish.onPressed, isNotNull);
      expect(find.text('Publish'), findsOneWidget);
      expect(find.text('Publish (complete draft first)'), findsNothing);

      final save = tester.widget<ElevatedButton>(
        find.byKey(const Key('knowledge-article-edit-save')),
      );
      expect(save.onPressed, isNotNull);
    });

    testWidgets('completed ticket draft keeps Publish available', (tester) async {
      final article = AdminArticle(
        id: 'done-1',
        title: 'Certificate of Enrollment',
        category: 'Student Records',
        published: false,
        content:
            'Submit the COE request at the Registrar with your student number and program.',
        displayContent:
            'Submit the COE request at the Registrar with your student number and program.',
        office: 'Office of the Registrar',
        kbOrigin: 'ticket_resolution',
        sourceTicketId: 'TK-2',
        needsManualCompletion: false,
      );

      await pumpEdit(tester, article: article);

      expect(find.byKey(const Key('ticket-kb-incomplete-banner')), findsNothing);
      final publish = tester.widget<OutlinedButton>(
        find.byKey(const Key('knowledge-article-edit-publish')),
      );
      expect(publish.onPressed, isNotNull);
      expect(find.text('Publish'), findsWidgets);
    });

    testWidgets('ordinary non-ticket draft has no incomplete warning',
        (tester) async {
      final article = AdminArticle(
        id: 'doc-1',
        title: 'Library hours',
        category: 'General Information',
        published: false,
        content: 'The main library is open weekdays from 8 AM to 5 PM.',
        displayContent: 'The main library is open weekdays from 8 AM to 5 PM.',
        office: 'Library',
        kbOrigin: 'document',
        needsManualCompletion: false,
      );

      await pumpEdit(tester, article: article);

      expect(find.byKey(const Key('ticket-kb-incomplete-banner')), findsNothing);
      final publish = tester.widget<OutlinedButton>(
        find.byKey(const Key('knowledge-article-edit-publish')),
      );
      expect(publish.onPressed, isNotNull);
    });
  });

  group('Compose KB article incomplete ticket drafts', () {
    Future<AuthController> signInOffice() async {
      final user = const AuthUser(
        id: 'office-1',
        email: 'office@example.edu',
        fullName: 'OSA',
        role: 'office',
        officeId: 'office-1',
        officeName: 'Office of the Registrar',
        emailVerified: true,
        createdAt: null,
        updatedAt: null,
      );
      final controller = AuthController(service: _FakeAuthService(user));
      await controller.login(
        const LoginRequest(email: 'office@example.edu', password: 'password'),
      );
      return controller;
    }

    Future<void> openCompose(
      WidgetTester tester, {
      required Map<String, dynamic> ticket,
    }) async {
      const size = Size(1200, 900);
      await tester.binding.setSurfaceSize(size);
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(() {
        tester.binding.setSurfaceSize(null);
        tester.view.resetPhysicalSize();
        tester.view.resetDevicePixelRatio();
      });
      final controller = await signInOffice();
      await tester.pumpWidget(
        AuthScope(
          controller: controller,
          child: MaterialApp(
            home: OfficeAssignedTicketsPage(
              initialSelectedTicketId: ticket['ticket_id']?.toString(),
              debugTickets: [ticket],
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.tap(find.text('Add to KB'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
    }

    testWidgets('incomplete compose draft shows banner but keeps Publish enabled',
        (tester) async {
      await openCompose(
        tester,
        ticket: {
          'ticket_id': 'TK-INC',
          'user_id': 'user-1',
          'user_name': 'Ana Santos',
          'original_question': 'Request for Certificate of Enrollment',
          'description': 'Need COE',
          'status': 'Resolved',
          'priority': 'Medium',
          'category': 'Student Records',
          'assigned_office': 'Office of the Registrar',
          'assigned_office_name': 'Office of the Registrar',
          'created_at': '2026-09-13T02:24:00Z',
          'updated_at': '2026-09-13T02:24:00Z',
          // Keep conversion status at none so the editor does not attempt a
          // live GET /kb-article during widget tests.
          'kb_conversion_status': 'none',
          'kb_needs_manual_completion': true,
          'messages': [
            {
              'id': 'm2',
              'ticket_id': 'TK-INC',
              'sender_id': 'office-1',
              'sender_role': 'office',
              'sender_name': 'Registrar',
              'message':
                  'You\'re welcome!\n\n$ticketKbCompletionMarker\n\nThank you!',
              'created_at': '2026-09-13T03:00:00Z',
              'is_internal': false,
            },
          ],
        },
      );

      expect(find.text('Compose KB article'), findsOneWidget);
      expect(find.byKey(const Key('ticket-kb-incomplete-banner')), findsOneWidget);
      final publish = tester.widget<ElevatedButton>(
        find.byKey(const Key('ticket-kb-publish')),
      );
      expect(publish.onPressed, isNotNull);
      expect(find.text('Publish'), findsWidgets);
      expect(find.text('Publish (complete draft first)'), findsNothing);
      // App bar Save draft stays enabled for incomplete drafts.
      final saveFinder = find.byKey(const Key('ticket-kb-save-draft'));
      expect(saveFinder, findsWidgets);
      final saveButton = tester.widget<TextButton>(saveFinder.first);
      expect(saveButton.onPressed, isNotNull);
    });

    testWidgets('ordinary compose draft keeps Publish enabled', (tester) async {
      await openCompose(
        tester,
        ticket: {
          'ticket_id': 'TK-OK',
          'user_id': 'user-1',
          'user_name': 'Ana Santos',
          'original_question': 'Good moral certificate',
          'description': 'I need the steps.',
          'status': 'Resolved',
          'priority': 'Medium',
          'category': 'Student Records',
          'assigned_office': 'Office of the Registrar',
          'assigned_office_name': 'Office of the Registrar',
          'created_at': '2026-09-13T02:24:00Z',
          'updated_at': '2026-09-13T02:24:00Z',
          'messages': [
            {
              'id': 'm2',
              'ticket_id': 'TK-OK',
              'sender_id': 'office-1',
              'sender_role': 'office',
              'sender_name': 'Registrar',
              'message':
                  'Please follow these steps to request a good moral certificate from OSAS.',
              'created_at': '2026-09-13T03:00:00Z',
              'is_internal': false,
            },
          ],
        },
      );

      expect(find.byKey(const Key('ticket-kb-incomplete-banner')), findsNothing);
      final publish = tester.widget<ElevatedButton>(
        find.byKey(const Key('ticket-kb-publish')),
      );
      expect(publish.onPressed, isNotNull);
    });
  });
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
