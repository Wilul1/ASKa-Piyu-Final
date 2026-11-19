import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/design_tokens.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/login_page.dart';
import 'package:aska_piyu/screens/student_home.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/widgets/auth_split_shell.dart';
import 'package:aska_piyu/widgets/phone_layout.dart';
import 'package:aska_piyu/widgets/public_site_header.dart';
import 'package:aska_piyu/widgets/student_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('design tokens keep the maroon web palette', () {
    expect(DesignTokens.maroon, const Color(0xFF5C0A0F));
    expect(DesignTokens.primaryBlue, DesignTokens.maroon);
    expect(DesignTokens.pageBg, const Color(0xFFF7F5F6));
    expect(DesignTokens.statusOpen, isNot(const Color(0xFF2563EB)));
    expect(DesignTokens.maroonWash, const Color(0xFFF8E8EA));
  });

  testWidgets('phone home uses the public header menu without overflow',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      AuthScope(
        controller: AuthController(service: _NoopAuthService()),
        child: const MaterialApp(home: StudentHomePage()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.byType(PublicSiteHeader), findsOneWidget);
    expect(find.byIcon(Icons.menu_rounded), findsOneWidget);
    expect(isPhoneLayout(tester.element(find.byType(PublicSiteHeader))), isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('phone login keeps maroon brand chrome and form actions',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      AuthScope(
        controller: AuthController(service: _NoopAuthService()),
        child: const MaterialApp(home: LoginPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(AuthSplitShell), findsOneWidget);
    expect(find.text('Sign In'), findsWidgets);
    expect(find.byType(AuthPrimaryButton), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('student empty state and primary button use brand colors',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(360, 740));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(
          elevatedButtonTheme: ElevatedButtonThemeData(
            style: DesignTokens.primaryButtonStyle(),
          ),
        ),
        home: Scaffold(
          body: StudentEmptyState(
            title: 'No tickets yet',
            message: 'Submit a support request when you need help.',
            action: StudentPrimaryButton(
              label: 'Submit Ticket',
              onPressed: () {},
              expand: true,
            ),
          ),
        ),
      ),
    );

    expect(find.text('No tickets yet'), findsOneWidget);
    final button = tester.widget<ElevatedButton>(
      find.widgetWithText(ElevatedButton, 'Submit Ticket'),
    );
    final bg = button.style?.backgroundColor?.resolve({});
    expect(bg, DesignTokens.maroon);
    expect(tester.takeException(), isNull);
  });

  testWidgets('larger phone and tablet breakpoints stay stable', (tester) async {
    for (final size in const [Size(430, 932), Size(768, 1024)]) {
      await tester.binding.setSurfaceSize(size);
      await tester.pumpWidget(
        AuthScope(
          controller: AuthController(service: _NoopAuthService()),
          child: const MaterialApp(home: StudentHomePage()),
        ),
      );
      await tester.pump();
      expect(find.byType(PublicSiteHeader), findsOneWidget);
      expect(tester.takeException(), isNull);
    }
    await tester.binding.setSurfaceSize(null);
  });
}

class _NoopAuthService extends AuthService {
  @override
  Future<String?> readAccessToken() async => null;

  @override
  Future<void> storeAccessToken(String token, {required bool persist}) async {}

  @override
  Future<void> clearAccessToken() async {}

  @override
  Future<AuthResponse> login(LoginRequest payload) {
    throw UnimplementedError();
  }

  @override
  Future<AuthResponse> signup(SignupRequest payload) {
    throw UnimplementedError();
  }
}
