import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/knowledge_base_page.dart';
import 'package:aska_piyu/services/auth_service.dart';

/// Covers KnowledgeBasePage's new initialArticleId entry point (used by the
/// chatbot's "open the public Knowledge Base article" citation link -- see
/// chatbot_page_test.dart's own citation-link tests for the chatbot side).
/// There is no HTTP-mocking seam in this codebase's widget tests, so the
/// *successful* open (GET /kb/articles/{id} returning 200) can't be
/// exercised directly here; what IS verified is the failure path this
/// sandbox's unreachable backend always takes -- it must fail safely
/// (a snackbar, no crash, no stuck/broken navigation state), and the
/// feature must stay a no-op whenever initialArticleId isn't set.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  AuthUser studentUser() {
    return const AuthUser(
      id: 'student-1',
      email: 'student@example.edu',
      fullName: 'Juan Dela Cruz',
      role: 'student',
      officeId: null,
      officeName: null,
      emailVerified: true,
      createdAt: null,
      updatedAt: null,
    );
  }

  Future<void> pumpKnowledgeBase(
    WidgetTester tester, {
    String? initialArticleId,
  }) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final controller = AuthController(service: _FakeAuthService(studentUser()));
    await controller.login(
      const LoginRequest(email: 'student@example.edu', password: 'password'),
    );
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(
          home: KnowledgeBasePage(initialArticleId: initialArticleId),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets(
      'with no initialArticleId, the page loads the normal list and never '
      'shows the article-unavailable snackbar', (tester) async {
    await pumpKnowledgeBase(tester);

    expect(
      find.text('That article is unavailable.'),
      findsNothing,
    );
    expect(
      find.widgetWithText(TextField, 'Search articles, policies, offices...'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'with an initialArticleId, the unreachable backend in this sandbox '
      'fails safely -- a snackbar, no crash, and the list stays usable '
      '(no broken/stuck navigation state)', (tester) async {
    await pumpKnowledgeBase(tester, initialArticleId: 'article-abc-123');
    // Let the post-frame-scheduled fetch run and fail.
    await tester.pump(const Duration(milliseconds: 200));

    expect(find.text('That article is unavailable.'), findsOneWidget);
    // Still on the list page -- nothing was pushed on top of it.
    expect(
      find.widgetWithText(TextField, 'Search articles, policies, offices...'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'an empty-string initialArticleId behaves exactly like none -- no '
      'fetch attempt, no snackbar', (tester) async {
    await pumpKnowledgeBase(tester, initialArticleId: '   ');

    expect(find.text('That article is unavailable.'), findsNothing);
    expect(tester.takeException(), isNull);
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
