import 'package:flutter/material.dart';

import 'local_store.dart';

/// A student-controlled "reading comfort" preference -- warm cream
/// surfaces, a softer (warmer, less stark) dark text tone for shared
/// section titles, and a touch less raw brightness than the default
/// white/cool-grey chrome. Not dark mode: ASKa-Piyu's burgundy brand
/// color is never touched, and nothing here uses a semi-transparent
/// overlay (which would have softened button/dialog contrast along with
/// everything else) -- every value below is an ordinary opaque color
/// swap, so existing contrast between text and its background is
/// preserved exactly as designed, just on a warmer backdrop.
class EyeComfortColors {
  EyeComfortColors._();

  static const Color bg = Color(0xFFF6EFDD);
  static const Color cardBg = Color(0xFFFFFBF0);
  static const Color border = Color(0xFFE6D9B8);
  static const Color headerBg = Color(0xFFFFFBF0);
  static const Color ink = Color(0xFF3A332A);

  /// Warm, muted secondary-text tone -- darkened from an earlier
  /// 0xFF7A6F5C (computed ~4.15:1 against [bg], just under WCAG AA's
  /// 4.5:1 for normal-size text) to this value, which computes to
  /// ~5.44:1 against [bg] and ~6.03:1 against [cardBg] -- comfortable
  /// margin above 4.5:1 in both places this is actually used, while
  /// staying visibly lighter/softer than [ink] so the muted/primary
  /// text hierarchy still reads correctly. Contrast ratios computed
  /// directly from these sRGB values via the standard WCAG relative-
  /// luminance formula, not sampled from a screenshot.
  static const Color muted = Color(0xFF6B5F4D);
}

/// Bumped by EyeComfortController -- a student toggles this once in
/// Account & Settings, and it then applies everywhere the shared
/// StudentPanel/StudentInkCard/StudentSectionTitle widgets and each
/// page's own root Scaffold read it, via EyeComfortScope.isEnabled(context).
/// Mirrors the existing AuthScope/KbWorkspaceScope convention in
/// main.dart (a ChangeNotifier wrapped in an InheritedNotifier) rather
/// than introducing a new state-management pattern.
class EyeComfortController extends ChangeNotifier {
  bool _enabled = false;

  bool get enabled => _enabled;

  /// Loads the persisted preference. Deliberately not read in the
  /// constructor: _MyAppState constructs this controller synchronously
  /// while the widget tree is first building, before LocalStore.init()
  /// is guaranteed ready in every context this controller might exist
  /// in (e.g. a widget test that pumps MyApp directly without mocking
  /// SharedPreferences at all). Call once, after the first frame --
  /// mirrors how AuthController.loadCurrentUser's own LocalStore reads
  /// only ever happen after its first await, never synchronously during
  /// construction.
  void load() {
    final stored = LocalStore.getEyeComfortPreference();
    if (stored != _enabled) {
      _enabled = stored;
      notifyListeners();
    }
  }

  Future<void> setEnabled(bool value) async {
    if (_enabled == value) return;
    _enabled = value;
    notifyListeners();
    await LocalStore.setEyeComfortPreference(value);
  }
}

class EyeComfortScope extends InheritedNotifier<EyeComfortController> {
  const EyeComfortScope({
    super.key,
    required EyeComfortController controller,
    required super.child,
  }) : super(notifier: controller);

  /// For the one call site that actually changes the preference (the
  /// Account & Settings toggle) -- the real app shell (main.dart) always
  /// provides a scope, so a missing one here is a genuine wiring bug,
  /// not a case to degrade gracefully from.
  static EyeComfortController of(BuildContext context) {
    final scope =
        context.dependOnInheritedWidgetOfExactType<EyeComfortScope>();
    assert(scope != null, 'EyeComfortScope was not found in the widget tree.');
    return scope!.notifier!;
  }

  /// For every widget that only *reads* the preference to pick a color.
  /// Defaults to false (the existing default appearance) when no scope
  /// is present, rather than throwing -- this lets every other widget
  /// test in the app keep pumping My Tickets / Knowledge Base / the
  /// shared header / student_ui.dart cards directly, exactly as they did
  /// before Eye Comfort existed, with no EyeComfortScope wrapper needed
  /// unless a test specifically wants to exercise Eye Comfort itself.
  static bool isEnabled(BuildContext context) {
    final scope =
        context.dependOnInheritedWidgetOfExactType<EyeComfortScope>();
    return scope?.notifier?.enabled ?? false;
  }
}
