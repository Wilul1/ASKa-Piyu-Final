import 'package:flutter/material.dart';

class DesignTokens {
  static const Color maroon = Color(0xFF7B1113);
  static const Color gold = Color(0xFFD4A017);
  static const Color ink = Color(0xFF1F2937);
  static const Color muted = Color(0xFF64748B);
  static const Color border = Color(0xFFE5EAF1);
  static const Color bgGrey = Color(0xFFF8F9FC);
  static const Color cardBg = Color(0xFFFFFFFF);
  static const Color primaryBlue = maroon;
  static const double spacing = 16.0;
  static const double radius = 18.0;

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
}
