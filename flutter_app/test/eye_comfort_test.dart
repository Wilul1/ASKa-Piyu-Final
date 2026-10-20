import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:aska_piyu/design_tokens.dart';
import 'package:aska_piyu/services/eye_comfort.dart';
import 'package:aska_piyu/services/local_store.dart';
import 'package:aska_piyu/widgets/student_ui.dart';

/// Covers Eye Comfort's persistence (LocalStore round-trip, mirroring the
/// existing Remember-Me preference pattern) and its theme-level
/// application via the safe EyeComfortScope.isEnabled(context) accessor,
/// independent of any one page -- page-specific coverage (the toggle
/// itself, the Account & Settings page background) lives in
/// settings_page_test.dart.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    LocalStore.resetForTest();
    SharedPreferences.setMockInitialValues(const {});
  });

  group('persistence', () {
    test('defaults to off when nothing has been saved yet', () async {
      await LocalStore.init();
      expect(LocalStore.getEyeComfortPreference(), isFalse);
    });

    test(
        'setEyeComfortPreference persists and getEyeComfortPreference reads '
        'it back', () async {
      await LocalStore.init();

      await LocalStore.setEyeComfortPreference(true);
      expect(LocalStore.getEyeComfortPreference(), isTrue);

      await LocalStore.setEyeComfortPreference(false);
      expect(LocalStore.getEyeComfortPreference(), isFalse);
    });

    test(
        'a fresh EyeComfortController starts off (even if a preference is '
        'already saved) until load() is called', () async {
      SharedPreferences.setMockInitialValues({'aska_eye_comfort_pref': true});
      await LocalStore.init();

      final controller = EyeComfortController();
      expect(controller.enabled, isFalse);

      controller.load();
      expect(controller.enabled, isTrue);
    });

    test(
        'EyeComfortController.setEnabled updates state, notifies listeners '
        'exactly once, and persists -- survives a fresh controller/load() '
        '("app restart")', () async {
      await LocalStore.init();
      final controller = EyeComfortController();
      var notifyCount = 0;
      controller.addListener(() => notifyCount++);

      await controller.setEnabled(true);
      expect(controller.enabled, isTrue);
      expect(notifyCount, 1);
      expect(LocalStore.getEyeComfortPreference(), isTrue);

      // Setting the same value again is a no-op -- no redundant
      // notify/write.
      await controller.setEnabled(true);
      expect(notifyCount, 1);

      // A brand-new controller (simulating a fresh app launch) picks up
      // the persisted value once loaded.
      final restarted = EyeComfortController();
      expect(restarted.enabled, isFalse);
      restarted.load();
      expect(restarted.enabled, isTrue);
    });
  });

  group('theme application (StudentPanel, representative of the shared '
      'surface used by My Tickets, Submit Ticket, Knowledge Base, and '
      'Account & Settings)', () {
    Future<void> pumpPanel(
      WidgetTester tester,
      EyeComfortController controller,
    ) {
      return tester.pumpWidget(
        EyeComfortScope(
          controller: controller,
          child: const MaterialApp(
            home: Scaffold(body: StudentPanel(child: Text('content'))),
          ),
        ),
      );
    }

    Color panelColor(WidgetTester tester) {
      final decoration =
          tester.widget<DecoratedBox>(find.byType(DecoratedBox).first).decoration
              as BoxDecoration;
      return decoration.color!;
    }

    testWidgets('uses the existing default card background when Eye '
        'Comfort is off', (tester) async {
      await LocalStore.init();
      await pumpPanel(tester, EyeComfortController());

      expect(panelColor(tester), DesignTokens.cardBg);
    });

    testWidgets('switches to the warm cream card background when Eye '
        'Comfort is on', (tester) async {
      await LocalStore.init();
      final controller = EyeComfortController();
      await controller.setEnabled(true);
      await pumpPanel(tester, controller);

      expect(panelColor(tester), EyeComfortColors.cardBg);
    });

    testWidgets('a page with no EyeComfortScope at all safely defaults to '
        'the existing look -- isEnabled() never throws', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(body: StudentPanel(child: Text('content'))),
        ),
      );

      expect(panelColor(tester), DesignTokens.cardBg);
      expect(tester.takeException(), isNull);
    });
  });

  group('secondary-text contrast (WCAG AA, computed from the sRGB values '
      'directly -- not sampled from a screenshot)', () {
    // Standard relative-luminance / contrast-ratio formulas
    // (https://www.w3.org/TR/WCAG21/#contrast-minimum).
    double linearizeChannel(double c) =>
        c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4).toDouble();

    double relativeLuminance(Color color) {
      final r = linearizeChannel(color.r);
      final g = linearizeChannel(color.g);
      final b = linearizeChannel(color.b);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }

    double contrastRatio(Color a, Color b) {
      final la = relativeLuminance(a);
      final lb = relativeLuminance(b);
      final lighter = la > lb ? la : lb;
      final darker = la > lb ? lb : la;
      return (lighter + 0.05) / (darker + 0.05);
    }

    const aaNormalText = 4.5;

    test('EyeComfortColors.muted clears 4.5:1 against the warm page '
        'background', () {
      expect(
        contrastRatio(EyeComfortColors.muted, EyeComfortColors.bg),
        greaterThanOrEqualTo(aaNormalText),
      );
    });

    test('EyeComfortColors.muted clears 4.5:1 against the warm card '
        'background too', () {
      expect(
        contrastRatio(EyeComfortColors.muted, EyeComfortColors.cardBg),
        greaterThanOrEqualTo(aaNormalText),
      );
    });

    test('EyeComfortColors.ink (section titles) clears 4.5:1 against both '
        'warm surfaces, with a wide margin', () {
      expect(
        contrastRatio(EyeComfortColors.ink, EyeComfortColors.bg),
        greaterThanOrEqualTo(aaNormalText),
      );
      expect(
        contrastRatio(EyeComfortColors.ink, EyeComfortColors.cardBg),
        greaterThanOrEqualTo(aaNormalText),
      );
    });

    test('regression guard: the previous muted value (0xFF7A6F5C) would '
        'have failed against the page background -- documents why it was '
        'replaced, not just that the new one passes', () {
      const previousMuted = Color(0xFF7A6F5C);
      expect(
        contrastRatio(previousMuted, EyeComfortColors.bg),
        lessThan(aaNormalText),
      );
    });

    test('the existing default DesignTokens.muted is left exactly as-is '
        '(not globally altered) -- still whatever it already was against '
        'plain white, Eye Comfort off', () {
      expect(DesignTokens.muted, const Color(0xFF64748B));
    });
  });
}
