import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/settings_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/services/eye_comfort.dart';
import 'package:aska_piyu/services/local_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  AuthUser studentUser({bool emailVerified = true}) {
    return AuthUser(
      id: 'student-1',
      email: 'student@example.edu',
      fullName: 'Juan Dela Cruz',
      role: 'student',
      officeId: null,
      officeName: null,
      emailVerified: emailVerified,
      createdAt: null,
      updatedAt: null,
    );
  }

  Future<void> pumpSettings(
    WidgetTester tester, {
    AuthUser? user,
    Size size = const Size(1200, 900),
    EyeComfortController? eyeComfort,
  }) async {
    // SettingsPage embeds PublicSiteHeader, which reads MediaQuery.sizeOf
    // directly rather than via a LayoutBuilder; setting tester.view
    // directly (not tester.binding.setSurfaceSize) is what reliably
    // propagates to it in this environment.
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final controller = AuthController(service: _FakeAuthService(user ?? studentUser()));
    await controller.login(
      const LoginRequest(email: 'student@example.edu', password: 'password'),
    );

    final settingsPage = const MaterialApp(home: SettingsPage());
    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        // Most tests here don't care about Eye Comfort at all, so they
        // pass no controller -- EyeComfortScope.isEnabled's safe default
        // (off, the existing look) already covers that case without a
        // wrapper, same as the real app's own default-off behavior.
        child: eyeComfort == null
            ? settingsPage
            : EyeComfortScope(controller: eyeComfort, child: settingsPage),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('shows the signed-in user\'s name, email, and role',
      (tester) async {
    await pumpSettings(tester);

    expect(find.text('Juan Dela Cruz'), findsOneWidget);
    expect(find.text('student@example.edu'), findsOneWidget);
    expect(find.text('Student'), findsOneWidget);
  });

  testWidgets('a verified user sees "Verified", never a tappable pending link',
      (tester) async {
    await pumpSettings(tester, user: studentUser(emailVerified: true));

    expect(find.text('Verified'), findsOneWidget);
    expect(find.textContaining('Pending'), findsNothing);
  });

  testWidgets('an unverified user sees the pending verification action',
      (tester) async {
    await pumpSettings(tester, user: studentUser(emailVerified: false));

    expect(find.textContaining('Pending'), findsOneWidget);
    expect(find.text('Verified'), findsNothing);
  });

  testWidgets('Change password opens a dialog with the existing fields',
      (tester) async {
    await pumpSettings(tester);

    await tester.tap(find.text('Change password'));
    await tester.pumpAndSettle();

    expect(find.text('Change password'), findsWidgets);
    expect(find.text('Current password'), findsOneWidget);
    expect(find.text('New password'), findsOneWidget);
    expect(find.text('Confirm new password'), findsOneWidget);
  });

  testWidgets('Change password validation is preserved (mismatched confirm)',
      (tester) async {
    await pumpSettings(tester);

    await tester.tap(find.text('Change password'));
    await tester.pumpAndSettle();

    await tester.enterText(find.widgetWithText(TextFormField, 'Current password'), 'oldpass123');
    await tester.enterText(find.widgetWithText(TextFormField, 'New password'), 'newpassword1');
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Confirm new password'),
      'different1',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Update password'));
    await tester.pumpAndSettle();

    expect(find.text('Passwords do not match.'), findsOneWidget);
    // The dialog stays open on a validation failure -- no request was sent.
    expect(find.text('Update password'), findsOneWidget);
  });

  testWidgets(
      'submitting a well-formed change fails gracefully in this sandbox '
      '(no backend reachable), never crashes', (tester) async {
    await pumpSettings(tester);

    await tester.tap(find.text('Change password'));
    await tester.pumpAndSettle();

    await tester.enterText(find.widgetWithText(TextFormField, 'Current password'), 'oldpass123');
    await tester.enterText(find.widgetWithText(TextFormField, 'New password'), 'newpassword1');
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Confirm new password'),
      'newpassword1',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Update password'));
    await tester.pumpAndSettle();

    // No reachable backend in this sandbox: the request fails, surfaced
    // as an inline error inside the still-open dialog, not a crash.
    expect(find.byType(AlertDialog), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Sign out is present and tappable on the Account page',
      (tester) async {
    await pumpSettings(tester);

    expect(find.text('Sign out'), findsOneWidget);
    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });

  // --- Preferences: Eye Comfort --------------------------------------------

  group('Eye Comfort', () {
    setUp(() {
      LocalStore.resetForTest();
      SharedPreferences.setMockInitialValues(const {});
    });

    testWidgets('no Notifications section exists -- notifications stay in '
        'Mailbox only', (tester) async {
      await pumpSettings(tester);

      expect(find.textContaining('Notification'), findsNothing);
    });

    testWidgets('the Preferences toggle is present, labeled "Eye Comfort", '
        'and off by default', (tester) async {
      await LocalStore.init();
      await pumpSettings(tester, eyeComfort: EyeComfortController());

      expect(find.text('Eye Comfort'), findsOneWidget);
      final toggle = tester.widget<Switch>(find.byType(Switch));
      expect(toggle.value, isFalse);
    });

    testWidgets(
        'tapping the toggle turns Eye Comfort on, updates the switch, '
        'changes the page background, and persists the choice',
        (tester) async {
      await LocalStore.init();
      final controller = EyeComfortController();
      await pumpSettings(tester, eyeComfort: controller);

      Color scaffoldBg() =>
          tester.widget<Scaffold>(find.byType(Scaffold).first).backgroundColor!;

      // Existing default appearance, unchanged while off.
      expect(scaffoldBg(), const Color(0xFFF3F4F6));

      await tester.tap(find.byType(Switch));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(
        tester.widget<Switch>(find.byType(Switch)).value,
        isTrue,
      );
      expect(scaffoldBg(), EyeComfortColors.bg);
      expect(controller.enabled, isTrue);
      expect(LocalStore.getEyeComfortPreference(), isTrue);
    });

    testWidgets(
        'Eye Comfort survives navigation -- a controller already on stays '
        'on, and the preference reloads as on after a simulated restart',
        (tester) async {
      await LocalStore.init();
      final controller = EyeComfortController();
      await controller.setEnabled(true);

      await pumpSettings(tester, eyeComfort: controller);
      expect(
        tester.widget<Switch>(find.byType(Switch)).value,
        isTrue,
      );

      // Simulated app restart: a brand-new controller, loaded fresh from
      // the same (mocked) persisted storage -- not the same in-memory
      // instance.
      final restarted = EyeComfortController();
      restarted.load();
      expect(restarted.enabled, isTrue);

      await pumpSettings(tester, eyeComfort: restarted);
      expect(
        tester.widget<Switch>(find.byType(Switch)).value,
        isTrue,
      );
    });

    testWidgets(
        'turning Eye Comfort back off restores the existing default '
        'appearance and persists', (tester) async {
      await LocalStore.init();
      final controller = EyeComfortController();
      await controller.setEnabled(true);
      await pumpSettings(tester, eyeComfort: controller);

      await tester.tap(find.byType(Switch));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(
        tester.widget<Switch>(find.byType(Switch)).value,
        isFalse,
      );
      expect(
        tester.widget<Scaffold>(find.byType(Scaffold).first).backgroundColor,
        const Color(0xFFF3F4F6),
      );
      expect(LocalStore.getEyeComfortPreference(), isFalse);
    });
  });

  testWidgets(
      'no redundant side nav remains -- Account is the only section and the '
      'old single-item nav was removed', (tester) async {
    await pumpSettings(tester, size: const Size(1200, 900));

    // The old side nav's own "Settings" section label is gone.
    expect(find.text('Settings'), findsNothing);
  });

  // --- Responsive layout at required widths --------------------------------

  for (final width in <double>[360, 600, 900, 1400]) {
    testWidgets('the Account page has no overflow at width ${width.toInt()}px',
        (tester) async {
      final unexpectedErrors = <String>[];
      final previousOnError = FlutterError.onError;
      FlutterError.onError = (details) {
        unexpectedErrors.add(details.toString());
        previousOnError?.call(details);
      };
      addTearDown(() => FlutterError.onError = previousOnError);

      await pumpSettings(tester, size: Size(width, 900));

      expect(unexpectedErrors, isEmpty);
      expect(find.text('Account'), findsWidgets);
      expect(find.text('Juan Dela Cruz'), findsOneWidget);
      expect(find.text('Change password'), findsOneWidget);
      expect(find.text('Sign out'), findsOneWidget);
    });
  }
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
