import 'package:flutter/material.dart';

/// Brand maroon used on public site / chat chrome (matches logo & chat pill).
const Color kBrandMaroon = Color(0xFF5C0A0F);

/// Shared visual language for the current web redesign, reused on phone layouts.
class DesignTokens {
  static const Color maroon = kBrandMaroon;
  static const Color maroonSoft = Color(0xFF6E1016);
  static const Color maroonWash = Color(0xFFF8E8EA);
  static const Color gold = Color(0xFFD4A017);
  static const Color ink = Color(0xFF1F2937);
  static const Color muted = Color(0xFF64748B);
  static const Color border = Color(0xFFE5EAF1);
  static const Color line = Color(0xFFE6E8EE);
  static const Color bgGrey = Color(0xFFF8F9FC);
  /// Warm page wash used by Knowledge Base / My Tickets / Account.
  static const Color pageBg = Color(0xFFF7F5F6);
  static const Color cardBg = Color(0xFFFFFFFF);
  /// Kept as an alias so older call sites keep compiling; always maroon.
  static const Color primaryBlue = maroon;
  static const double spacing = 16.0;

  /// Equal left and right inset for the desktop Knowledge Base header
  /// and page column, as a fraction of the viewport. Keeps that column
  /// about 87% of the width and centered.
  static const double kbDesktopSideInset = 0.065;
  static const double radius = 18.0;
  static const double radiusSm = 12.0;
  static const double radiusLg = 22.0;

  /// Semantic ticket/status accents — warm palette, no electric Material blue.
  static const Color statusOpen = Color(0xFF9F1239);
  static const Color statusInProgress = Color(0xFFC2410C);
  static const Color statusResolved = Color(0xFF7C3AED);
  static const Color statusClosed = Color(0xFF15803D);
  static const Color statusUrgent = Color(0xFFDC2626);

  /// Admin shell surfaces (professional dashboard).
  /// Deep maroon sidebar (brand), not charcoal/blue-gray.
  static const Color adminSidebarBg = Color(0xFF4A0A0E);
  static const Color adminSidebarText = Color(0xFFF3D5D8);
  static const Color adminSidebarMuted = Color(0xFFD4A0A5);
  static const Color adminSidebarActive = Color(0xFF6E1016);
  static const Color adminSurface = Color(0xFFF5F7FB);
  static const double adminRadius = 12.0;
  static const double adminSidebarWidth = 250.0;

  static const TextStyle h1 =
      TextStyle(fontSize: 32, fontWeight: FontWeight.w900, color: ink);
  static const TextStyle h2 =
      TextStyle(fontSize: 22, fontWeight: FontWeight.w900, color: ink);
  static const TextStyle subtitle =
      TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: ink);
  static const TextStyle body = TextStyle(fontSize: 14, color: ink);

  static List<BoxShadow> softShadow([double opacity = 0.055]) {
    return [
      BoxShadow(
        color: Colors.black.withValues(alpha: opacity),
        blurRadius: 18,
        offset: const Offset(0, 10),
      ),
    ];
  }

  /// Compact phone padding for public content columns.
  static EdgeInsets phonePagePadding({
    double horizontal = 16,
    double top = 14,
    double bottom = 24,
  }) {
    return EdgeInsets.fromLTRB(horizontal, top, horizontal, bottom);
  }

  static ButtonStyle primaryButtonStyle({
    double height = 48,
    double radius = radiusSm,
  }) {
    return ElevatedButton.styleFrom(
      backgroundColor: maroon,
      foregroundColor: Colors.white,
      disabledBackgroundColor: const Color(0xFFE2E8F0),
      disabledForegroundColor: muted,
      elevation: 0,
      minimumSize: Size(48, height),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(radius),
      ),
      textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
    );
  }

  static ButtonStyle secondaryButtonStyle({
    double height = 48,
    double radius = radiusSm,
  }) {
    return OutlinedButton.styleFrom(
      foregroundColor: maroon,
      side: const BorderSide(color: maroon),
      minimumSize: Size(48, height),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(radius),
      ),
      textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
    );
  }

  static InputDecorationTheme inputDecorationTheme() {
    OutlineInputBorder border([Color color = DesignTokens.border]) {
      return OutlineInputBorder(
        borderRadius: BorderRadius.circular(radiusSm),
        borderSide: BorderSide(color: color),
      );
    }

    return InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      border: border(),
      enabledBorder: border(),
      focusedBorder: border(maroon),
      errorBorder: border(statusUrgent),
      hintStyle: const TextStyle(color: muted, fontSize: 14),
    );
  }
}
