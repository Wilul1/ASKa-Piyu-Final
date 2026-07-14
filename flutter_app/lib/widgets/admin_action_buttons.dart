import 'package:flutter/material.dart';

import '../design_tokens.dart';

/// Shared maroon/white admin action buttons (text-only, no icons).
///
/// Primary and secondary share the same height, padding, and radius so
/// paired actions (e.g. Extract + Index) look balanced.
class AdminPrimaryButton extends StatelessWidget {
  const AdminPrimaryButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.minWidth,
    this.expand = false,
  });

  static const double height = 46;
  static const EdgeInsetsGeometry padding =
      EdgeInsets.symmetric(horizontal: 18, vertical: 12);
  static const double radius = 14;

  final String label;
  final VoidCallback? onPressed;
  final double? minWidth;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    final child = ConstrainedBox(
      constraints: BoxConstraints(
        minHeight: height,
        minWidth: minWidth ?? 0,
      ),
      child: DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(radius),
          gradient: enabled
              ? const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [
                    Color(0xFF9A1B1E),
                    DesignTokens.maroon,
                    Color(0xFF5C0C0E),
                  ],
                )
              : null,
          color: enabled ? null : const Color(0xFFCBD5E1),
          boxShadow: enabled
              ? [
                  BoxShadow(
                    color: DesignTokens.maroon.withValues(alpha: 0.18),
                    blurRadius: 8,
                    offset: const Offset(0, 3),
                  ),
                ]
              : null,
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: onPressed,
            borderRadius: BorderRadius.circular(radius),
            child: Padding(
              padding: padding,
              child: Center(
                child: Text(
                  label,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: enabled ? Colors.white : const Color(0xFF64748B),
                    fontWeight: FontWeight.w700,
                    fontSize: 14,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
    if (expand) {
      return SizedBox(width: double.infinity, child: child);
    }
    return child;
  }
}

class AdminSecondaryButton extends StatelessWidget {
  const AdminSecondaryButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.minWidth,
    this.expand = false,
  });

  static const double height = AdminPrimaryButton.height;
  static const EdgeInsetsGeometry padding = AdminPrimaryButton.padding;
  static const double radius = AdminPrimaryButton.radius;

  final String label;
  final VoidCallback? onPressed;
  final double? minWidth;
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    final child = ConstrainedBox(
      constraints: BoxConstraints(
        minHeight: height,
        minWidth: minWidth ?? 0,
      ),
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          foregroundColor: DesignTokens.maroon,
          backgroundColor: Colors.white,
          disabledForegroundColor: DesignTokens.muted,
          disabledBackgroundColor: const Color(0xFFF8FAFC),
          side: BorderSide(
            color: enabled ? DesignTokens.maroon : DesignTokens.border,
            width: 1.4,
          ),
          elevation: 0,
          minimumSize: Size(minWidth ?? 0, height),
          padding: padding,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(radius),
          ),
        ),
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
        ),
      ),
    );
    if (expand) {
      return SizedBox(width: double.infinity, child: child);
    }
    return child;
  }
}
