import 'package:flutter/material.dart';

import '../design_tokens.dart';

/// Full-screen maroon / white auth layout with LSPU brand panel.
class AuthSplitShell extends StatelessWidget {
  final Widget form;

  const AuthSplitShell({super.key, required this.form});

  static const maroon = Color(0xFF5C0A0F);

  void _goBack(BuildContext context) {
    final navigator = Navigator.of(context);
    if (navigator.canPop()) {
      navigator.pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final isNarrow = width < 860;

    return Scaffold(
      backgroundColor: Colors.white,
      body: isNarrow
          ? Column(
              children: [
                _BrandPanel(
                  compact: true,
                  onBack: () => _goBack(context),
                ),
                Expanded(
                  child: SafeArea(
                    top: false,
                    child: _FormPane(form: form),
                  ),
                ),
              ],
            )
          : Row(
              children: [
                Expanded(
                  flex: 5,
                  child: _BrandPanel(
                    compact: false,
                    onBack: () => _goBack(context),
                  ),
                ),
                Expanded(
                  flex: 6,
                  child: SafeArea(
                    child: _FormPane(form: form),
                  ),
                ),
              ],
            ),
    );
  }
}

class _FormPane extends StatelessWidget {
  final Widget form;

  const _FormPane({required this.form});

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.white,
      child: LayoutBuilder(
        builder: (context, constraints) {
          return SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 32),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                minHeight: constraints.maxHeight - 64,
                maxWidth: 420,
              ),
              child: Align(
                alignment: Alignment.center,
                child: SizedBox(
                  width: constraints.maxWidth.clamp(0, 420),
                  child: form,
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _BrandPanel extends StatelessWidget {
  final bool compact;
  final VoidCallback onBack;

  const _BrandPanel({
    required this.compact,
    required this.onBack,
  });

  @override
  Widget build(BuildContext context) {
    final logo = Image.asset(
      'assets/lspu_logo.png',
      width: compact ? 96 : 160,
      height: compact ? 96 : 160,
      fit: BoxFit.contain,
      filterQuality: FilterQuality.high,
      errorBuilder: (_, __, ___) => Icon(
        Icons.account_balance_rounded,
        size: compact ? 72 : 120,
        color: Colors.white,
      ),
    );

    final title = Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        logo,
        SizedBox(height: compact ? 12 : 20),
        Text(
          'Laguna State',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: Colors.white,
            fontSize: compact ? 18 : 26,
            fontWeight: FontWeight.w700,
            height: 1.2,
          ),
        ),
        Text(
          'Polytechnic University',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: Colors.white,
            fontSize: compact ? 18 : 26,
            fontWeight: FontWeight.w700,
            height: 1.2,
          ),
        ),
      ],
    );

    return ColoredBox(
      color: AuthSplitShell.maroon,
      child: SafeArea(
        child: Stack(
          children: [
            if (!compact)
              Positioned.fill(
                child: IgnorePointer(
                  child: CustomPaint(painter: _AuthWavePainter()),
                ),
              ),
            if (compact)
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 48, 20, 24),
                child: Center(child: title),
              )
            else
              Center(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 28),
                  child: title,
                ),
              ),
            Positioned(
              top: 4,
              left: 4,
              child: IconButton(
                tooltip: 'Back',
                onPressed: onBack,
                style: IconButton.styleFrom(
                  foregroundColor: Colors.white,
                  backgroundColor: Colors.white.withValues(alpha: 0.14),
                ),
                icon: const Icon(Icons.arrow_back_rounded, size: 22),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AuthWavePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    if (size.width <= 0 || size.height <= 0) return;

    final paint = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.fill;

    // Narrow soft edge only — keep maroon dominant.
    final path = Path()
      ..moveTo(size.width * 0.96, 0)
      ..cubicTo(
        size.width * 0.93,
        size.height * 0.30,
        size.width * 0.99,
        size.height * 0.55,
        size.width * 0.95,
        size.height * 0.78,
      )
      ..cubicTo(
        size.width * 0.93,
        size.height * 0.90,
        size.width * 0.97,
        size.height * 0.96,
        size.width * 0.96,
        size.height,
      )
      ..lineTo(size.width + 1, size.height)
      ..lineTo(size.width + 1, 0)
      ..close();

    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

InputDecoration authFieldDecoration(String hint) {
  return InputDecoration(
    hintText: hint,
    hintStyle: const TextStyle(
      color: Color(0xFF9CA3AF),
      fontWeight: FontWeight.w500,
    ),
    filled: true,
    fillColor: Colors.white,
    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: Color(0xFFD1D5DB)),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: Color(0xFFD1D5DB)),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: AuthSplitShell.maroon, width: 1.5),
    ),
    errorBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: Color(0xFFDC2626)),
    ),
    focusedErrorBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: Color(0xFFDC2626), width: 1.5),
    ),
  );
}

class AuthErrorBanner extends StatelessWidget {
  final String message;

  const AuthErrorBanner({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFFED7AA)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded, color: Color(0xFFC2410C)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(color: Color(0xFF9A3412), height: 1.35),
            ),
          ),
        ],
      ),
    );
  }
}

class AuthPrimaryButton extends StatelessWidget {
  final String label;
  final bool loading;
  final VoidCallback? onPressed;

  const AuthPrimaryButton({
    super.key,
    required this.label,
    required this.loading,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 48,
      child: ElevatedButton(
        onPressed: loading ? null : onPressed,
        style: ElevatedButton.styleFrom(
          backgroundColor: AuthSplitShell.maroon,
          foregroundColor: Colors.white,
          disabledBackgroundColor:
              AuthSplitShell.maroon.withValues(alpha: 0.65),
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
        child: loading
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2.2,
                  color: Colors.white,
                ),
              )
            : Text(
                label,
                style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  letterSpacing: 0.8,
                  fontSize: 14,
                ),
              ),
      ),
    );
  }
}

class AuthSecondaryButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;

  const AuthSecondaryButton({
    super.key,
    required this.label,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 48,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          foregroundColor: AuthSplitShell.maroon,
          side: const BorderSide(color: AuthSplitShell.maroon, width: 1.4),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
        child: Text(
          label,
          style: const TextStyle(
            fontWeight: FontWeight.w800,
            letterSpacing: 0.8,
            fontSize: 14,
          ),
        ),
      ),
    );
  }
}

class AuthOrDivider extends StatelessWidget {
  final String text;

  const AuthOrDivider({super.key, required this.text});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Expanded(child: Divider(color: Color(0xFFE5E7EB))),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Text(
            text,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
        const Expanded(child: Divider(color: Color(0xFFE5E7EB))),
      ],
    );
  }
}
