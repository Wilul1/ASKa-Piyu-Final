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

  // Where the fixed-position form panel begins, as a fraction of the full
  // viewport width. The decorative curved boundary (painted behind it,
  // full-bleed across the whole photo) bulges further left than this into
  // the photo side, so the white area visibly "intrudes" into the photo
  // without ever clipping the live form content itself -- the form's own
  // box always starts at this same safe fixed edge.
  static const double _formSplit = 0.55;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final isNarrow = width < 860;

    return Scaffold(
      backgroundColor: Colors.white,
      resizeToAvoidBottomInset: true,
      body:
          isNarrow
              ? Column(
                children: [
                  _BrandPanel(
                    compact: true,
                    keyboardOpen: false,
                    onBack: () => _goBack(context),
                  ),
                  Expanded(
                    child: SafeArea(top: false, child: _FormPane(form: form)),
                  ),
                ],
              )
              : Stack(
                children: [
                  Positioned.fill(
                    child: _BrandPanel(
                      compact: false,
                      keyboardOpen: false,
                      formSplit: _formSplit,
                      onBack: () => _goBack(context),
                    ),
                  ),
                  Positioned(
                    left: width * _formSplit,
                    right: 0,
                    top: 0,
                    bottom: 0,
                    child: ColoredBox(
                      color: Colors.white,
                      child: SafeArea(child: _FormPane(form: form)),
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
    return LayoutBuilder(
      builder: (context, constraints) {
        final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 48;
        // A wider usable column (was capped at 420) and a slight left bias
        // (instead of dead-center) so the form sits closer to the curved
        // boundary rather than stranded in the middle of a wide white
        // panel -- the panel itself is already comfortably narrower than
        // the full white area on large desktop widths.
        final maxFieldWidth = constraints.maxWidth >= 700 ? 560.0 : 500.0;
        return SingleChildScrollView(
          padding: EdgeInsets.symmetric(
            horizontal: 32,
            vertical: keyboardOpen ? 16 : 32,
          ),
          child: ConstrainedBox(
            constraints: BoxConstraints(
              minHeight:
                  keyboardOpen
                      ? 0
                      : (constraints.maxHeight - 64).clamp(0, double.infinity),
            ),
            child: Align(
              alignment:
                  keyboardOpen
                      ? Alignment.topCenter
                      : const Alignment(-0.15, 0),
              child: ConstrainedBox(
                constraints: BoxConstraints(maxWidth: maxFieldWidth),
                child: form,
              ),
            ),
          ),
        );
      },
    );
  }
}

class _BrandPanel extends StatelessWidget {
  final bool compact;
  final bool keyboardOpen;
  final VoidCallback onBack;
  // Only meaningful when !compact -- see AuthSplitShell._formSplit. Tells
  // the curved-boundary painter and the left content column where the
  // fixed-position white form panel begins, so neither ever reaches into
  // (or leaves an awkward gap before) that edge.
  final double formSplit;

  const _BrandPanel({
    required this.compact,
    required this.keyboardOpen,
    required this.onBack,
    this.formSplit = 1,
  });

  // Desktop-only: a pill with a "Back" label, sized to belong to the
  // spacious photo panel's own composition rather than floating as a tiny
  // debug-looking control.
  Widget _backControl() {
    return SafeArea(
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(24),
          onTap: onBack,
          child: Container(
            margin: const EdgeInsets.all(16),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.18),
              borderRadius: BorderRadius.circular(24),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.arrow_back_rounded, size: 18, color: Colors.white),
                SizedBox(width: 6),
                Text(
                  'Back',
                  style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // Compact/mobile-only: the header row is already tight (logo + full
  // university name), so this stays a small icon-only control, unchanged
  // from the previously approved mobile treatment.
  Widget _compactBackControl() {
    return SafeArea(
      bottom: false,
      child: IconButton(
        tooltip: 'Back',
        onPressed: onBack,
        style: IconButton.styleFrom(
          foregroundColor: Colors.white,
          backgroundColor: Colors.white.withValues(alpha: 0.14),
        ),
        icon: const Icon(Icons.arrow_back_rounded, size: 22),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // Mobile keeps a compact, solid-maroon header -- no campus photo here,
    // so decorative artwork never eats into the space before the form.
    if (compact) {
      final logo = Image.asset(
        'assets/lspu_logo.png',
        width: 48,
        height: 48,
        fit: BoxFit.contain,
        filterQuality: FilterQuality.high,
        errorBuilder:
            (_, __, ___) => const Icon(
              Icons.account_balance_rounded,
              size: 40,
              color: Colors.white,
            ),
      );
      // Full-width Row + Expanded (not mainAxisSize.min + Flexible): the
      // latter leaves the university name unbounded and overflows ~73px at
      // 390-wide viewports once the back control's left inset is reserved.
      final title = Row(
        children: [
          logo,
          const SizedBox(width: 12),
          const Expanded(
            child: Text(
              'Laguna State Polytechnic University',
              style: TextStyle(
                color: Colors.white,
                fontSize: 15,
                fontWeight: FontWeight.w700,
                height: 1.2,
              ),
            ),
          ),
        ],
      );
      return ColoredBox(
        color: AuthSplitShell.maroon,
        child: SafeArea(
          bottom: false,
          child: Stack(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(56, 14, 20, 14),
                child: title,
              ),
              Positioned(top: 0, left: 4, child: _compactBackControl()),
            ],
          ),
        ),
      );
    }

    // Desktop: a purpose-built graphic brand panel -- no campus photograph.
    // A layered maroon gradient base, soft abstract shapes, a restrained
    // academic watermark, dotted-grid accents, and multi-tone bottom waves
    // stand in for the photo, with the LSPU seal as the panel's clear
    // visual anchor.
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final height = constraints.maxHeight;
        final leftContentWidth = (width * 0.42).clamp(340.0, 480.0);
        // ~12% larger than the previous 130/150 -- a subtle bump, not a
        // redesign, so the seal reads as a stronger visual anchor between
        // the tightened text-block and ASKa-Piyu groups below.
        final sealSize = height < 760 ? 146.0 : 168.0;
        // Center the branding composition within the maroon panel's own
        // USABLE area (before the curved white boundary at `formSplit`),
        // not within the full viewport -- a fixed 44px left inset was
        // leaving a huge, unbalanced gap on the right as the panel got
        // wider, since `leftContentWidth` is capped at 480 while the
        // usable maroon area keeps growing. Clamped to never go below the
        // old fixed inset, so narrow desktop widths keep their existing
        // spacing instead of being pushed tighter.
        final usableMaroonWidth = width * formSplit;
        final contentLeftInset = ((usableMaroonWidth - leftContentWidth) / 2)
            .clamp(44.0, double.infinity);

        return Stack(
          fit: StackFit.expand,
          children: [
            // Deep maroon base with subtle tonal variation (lighter toward
            // the center, darker toward the edges) rather than a flat fill.
            const DecoratedBox(
              decoration: BoxDecoration(
                gradient: RadialGradient(
                  center: Alignment(-0.1, -0.2),
                  radius: 1.3,
                  colors: [Color(0xFF6E1017), AuthSplitShell.maroon],
                  stops: [0.0, 1.0],
                ),
              ),
            ),
            Positioned.fill(
              child: IgnorePointer(
                child: CustomPaint(painter: _TopAbstractShapesPainter()),
              ),
            ),
            // A large, extremely low-opacity academic watermark -- built
            // from an existing Material icon, not a substitute seal --
            // sitting behind the content, right of the text column.
            Positioned(
              right: -width * 0.06,
              top: height * 0.08,
              child: IgnorePointer(
                child: Opacity(
                  opacity: 0.05,
                  child: Icon(
                    Icons.auto_stories_rounded,
                    size: width * 0.34,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
            Positioned(
              left: leftContentWidth + 12,
              top: height * 0.10,
              child: IgnorePointer(
                child: CustomPaint(
                  size: const Size(72, 72),
                  painter: _DotGridPainter(opacity: 0.20),
                ),
              ),
            ),
            Positioned(
              right: width * (1 - formSplit) + 24,
              bottom: height * 0.14,
              child: IgnorePointer(
                child: CustomPaint(
                  size: const Size(64, 64),
                  painter: _DotGridPainter(opacity: 0.16),
                ),
              ),
            ),
            Positioned.fill(
              child: IgnorePointer(
                child: CustomPaint(painter: _AuthWavePainter()),
              ),
            ),
            Positioned.fill(
              child: IgnorePointer(
                child: CustomPaint(
                  painter: _CurvedBoundaryPainter(splitFraction: formSplit),
                ),
              ),
            ),
            SafeArea(
              child: Padding(
                padding: EdgeInsets.fromLTRB(contentLeftInset, 0, 24, 0),
                // Align loosens the incoming constraints for its child --
                // required because `Stack(fit: StackFit.expand)` gives this
                // whole non-Positioned subtree TIGHT constraints (exactly
                // the full panel size). Without loosening them here, the
                // SizedBox below can never actually shrink to
                // `leftContentWidth` (a tight minimum can only be grown,
                // never shrunk), so every child was really centering
                // within the full remaining panel width instead of the
                // intended narrower column -- invisible under the old
                // left-aligned layout, but very visible once children are
                // centered within that (wrongly wide) box.
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: SizedBox(
                    width: leftContentWidth,
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      // Centered (not start) so every child -- the text block,
                      // the seal, and the ASKa-Piyu line -- shares the SAME
                      // center axis within `leftContentWidth`, which is
                      // itself already centered in the usable maroon region
                      // via `contentLeftInset`. That composes to exactly
                      // `usableMaroonWidth / 2` for the seal's center, with
                      // no separate calculation needed.
                      crossAxisAlignment: CrossAxisAlignment.center,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Text(
                          'WELCOME TO',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.white70,
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 2.2,
                          ),
                        ),
                        const SizedBox(height: 10),
                        Text(
                          'Laguna State\nPolytechnic University',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: height < 760 ? 28 : 33,
                            fontWeight: FontWeight.w800,
                            height: 1.18,
                          ),
                        ),
                        const SizedBox(height: 14),
                        const Text(
                          'Your gateway to student support, information, '
                          'and services.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.white70,
                            fontSize: 14.5,
                            height: 1.45,
                          ),
                        ),
                        const SizedBox(height: 18),
                        // The seal is the panel's main identity element now
                        // that the photo is gone -- shown plainly, crisp,
                        // and at its natural aspect ratio (no circular
                        // backdrop plate).
                        Image.asset(
                          'assets/lspu_logo.png',
                          width: sealSize,
                          height: sealSize,
                          fit: BoxFit.contain,
                          filterQuality: FilterQuality.high,
                          errorBuilder:
                              (_, __, ___) => Icon(
                                Icons.account_balance_rounded,
                                size: sealSize * 0.8,
                                color: Colors.white,
                              ),
                        ),
                        const SizedBox(height: 12),
                        // "ASKa-Piyu" branding centered under the seal,
                        // flanked by thin dividers -- centered relative to
                        // the seal's own width, not the wider text column.
                        SizedBox(
                          width: sealSize + 60,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.center,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Divider(
                                      color: Colors.white.withValues(
                                        alpha: 0.35,
                                      ),
                                      thickness: 1,
                                    ),
                                  ),
                                  const Padding(
                                    padding: EdgeInsets.symmetric(
                                      horizontal: 10,
                                    ),
                                    child: Text(
                                      'ASKa-Piyu',
                                      style: TextStyle(
                                        color: Colors.white,
                                        fontSize: 15,
                                        fontWeight: FontWeight.w800,
                                      ),
                                    ),
                                  ),
                                  Expanded(
                                    child: Divider(
                                      color: Colors.white.withValues(
                                        alpha: 0.35,
                                      ),
                                      thickness: 1,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 6),
                              Text(
                                'University Knowledge & Support',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  color: Colors.white.withValues(alpha: 0.65),
                                  fontSize: 11.5,
                                  fontWeight: FontWeight.w600,
                                  letterSpacing: 0.6,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
            Positioned(top: 0, left: 0, child: _backControl()),
          ],
        );
      },
    );
  }
}

/// Two soft, large, extremely low-opacity blobs near the top of the panel
/// -- built with plain radial gradients, not an external image -- for a
/// subtle abstract accent behind the text.
class _TopAbstractShapesPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    if (size.width <= 0 || size.height <= 0) return;
    final paint1 =
        Paint()
          ..shader = RadialGradient(
            colors: [
              Colors.white.withValues(alpha: 0.07),
              Colors.white.withValues(alpha: 0.0),
            ],
          ).createShader(
            Rect.fromCircle(
              center: Offset(size.width * 0.78, -size.height * 0.05),
              radius: size.width * 0.30,
            ),
          );
    canvas.drawCircle(
      Offset(size.width * 0.78, -size.height * 0.05),
      size.width * 0.30,
      paint1,
    );

    final paint2 =
        Paint()
          ..shader = RadialGradient(
            colors: [
              const Color(0xFFE7B0B6).withValues(alpha: 0.06),
              const Color(0xFFE7B0B6).withValues(alpha: 0.0),
            ],
          ).createShader(
            Rect.fromCircle(
              center: Offset(size.width * 0.20, size.height * 0.05),
              radius: size.width * 0.22,
            ),
          );
    canvas.drawCircle(
      Offset(size.width * 0.20, size.height * 0.05),
      size.width * 0.22,
      paint2,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// A tiny decorative dot grid -- a restrained institutional accent, not a
/// literal pattern from the reference image.
class _DotGridPainter extends CustomPainter {
  final double opacity;

  const _DotGridPainter({required this.opacity});

  @override
  void paint(Canvas canvas, Size size) {
    final paint =
        Paint()
          ..color = Colors.white.withValues(alpha: opacity)
          ..style = PaintingStyle.fill;
    const spacing = 12.0;
    const dotRadius = 1.4;
    for (double y = 0; y < size.height; y += spacing) {
      for (double x = 0; x < size.width; x += spacing) {
        canvas.drawCircle(Offset(x, y), dotRadius, paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DotGridPainter oldDelegate) =>
      oldDelegate.opacity != opacity;
}

/// A single soft curve (not a straight vertical line) suggesting the white
/// form panel intruding into the photo side. This paints a decorative
/// shape only -- the live [_FormPane] content always sits in its own
/// fixed-position rectangle starting at [splitFraction], so nothing here
/// can ever visually clip real form fields; at the panel's own left edge
/// the curve resolves back to a flat seam so the two meet cleanly.
class _CurvedBoundaryPainter extends CustomPainter {
  final double splitFraction;

  const _CurvedBoundaryPainter({required this.splitFraction});

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width <= 0 || size.height <= 0) return;
    final baseX = size.width * splitFraction;
    // A single gentle bow -- mostly vertical, one smooth direction change,
    // no S-curve and no circular bite. Top and bottom deliberately land at
    // slightly different offsets (not mirrored) so the line still reads as
    // organic rather than a symmetric lens shape. Total horizontal range
    // is intentionally small (~0.035 * width, well under 70px even on a
    // very wide desktop) -- a restrained lean, not a dramatic curve.
    final top = Offset(baseX + size.width * 0.006, -size.height * 0.15);
    final middle = Offset(baseX - size.width * 0.028, size.height * 0.52);
    final bottom = Offset(baseX - size.width * 0.008, size.height * 1.15);

    final anchors = [top, middle, bottom];

    final path =
        Path()
          ..moveTo(size.width + 1, -1)
          ..lineTo(anchors.first.dx, anchors.first.dy);
    for (var i = 0; i < anchors.length - 1; i++) {
      final p0 = i == 0 ? anchors[i] : anchors[i - 1];
      final p1 = anchors[i];
      final p2 = anchors[i + 1];
      final p3 = (i + 2 < anchors.length) ? anchors[i + 2] : anchors[i + 1];
      final c1 = p1 + (p2 - p0) / 6;
      final c2 = p2 - (p3 - p1) / 6;
      path.cubicTo(c1.dx, c1.dy, c2.dx, c2.dy, p2.dx, p2.dy);
    }
    path
      ..lineTo(size.width + 1, size.height + 1)
      ..close();

    canvas.drawPath(
      path,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.fill,
    );
  }

  @override
  bool shouldRepaint(covariant _CurvedBoundaryPainter oldDelegate) =>
      oldDelegate.splitFraction != splitFraction;
}

/// Layered translucent wave bands across the lower portion of the panel --
/// several maroon/pink tones (not the photo-era white overlays, since the
/// base is now a flat maroon gradient) using the same Catmull-Rom-derived
/// cubic-through-anchors technique as the homepage/My Tickets heroes
/// (implemented fresh here, not shared), so this page reads as part of the
/// same ASKa-Piyu visual system while adding restrained depth.
class _AuthWavePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    if (size.width <= 0 || size.height <= 0) return;

    // Confined to roughly the bottom third, deepest layer lowest, so the
    // brand content above always sits on the plain gradient.
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFF8A1D24).withValues(alpha: 0.35),
      anchors: const [
        Offset(0.00, 0.70),
        Offset(0.35, 0.62),
        Offset(0.70, 0.74),
        Offset(1.00, 0.66),
      ],
    );
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFFC96A73).withValues(alpha: 0.22),
      anchors: const [
        Offset(0.00, 0.86),
        Offset(0.35, 0.80),
        Offset(0.70, 0.90),
        Offset(1.00, 0.82),
      ],
    );
    _paintLayer(
      canvas,
      size,
      color: Colors.white.withValues(alpha: 0.10),
      anchors: const [
        Offset(0.00, 0.98),
        Offset(0.40, 0.95),
        Offset(0.75, 1.00),
        Offset(1.00, 0.96),
      ],
    );
  }

  void _paintLayer(
    Canvas canvas,
    Size size, {
    required Color color,
    required List<Offset> anchors,
  }) {
    final pts = <Offset>[
      for (final a in anchors) Offset(size.width * a.dx, size.height * a.dy),
    ];
    final path =
        Path()
          ..moveTo(0, size.height)
          ..lineTo(pts.first.dx, pts.first.dy);
    for (var i = 0; i < pts.length - 1; i++) {
      final p0 = i == 0 ? pts[i] : pts[i - 1];
      final p1 = pts[i];
      final p2 = pts[i + 1];
      final p3 = (i + 2 < pts.length) ? pts[i + 2] : pts[i + 1];
      final c1 = p1 + (p2 - p0) / 6;
      final c2 = p2 - (p3 - p1) / 6;
      path.cubicTo(c1.dx, c1.dy, c2.dx, c2.dy, p2.dx, p2.dy);
    }
    path
      ..lineTo(size.width, size.height)
      ..close();
    canvas.drawPath(path, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// A bold static label above a field, matching the reference's separate
/// "Email" / "Password" headings (distinct from the lighter hint text
/// inside the box itself). Purely presentational -- wraps whatever field
/// is passed in without touching its controller/validator/behavior.
class AuthLabeledField extends StatelessWidget {
  final String label;
  final Widget field;

  const AuthLabeledField({super.key, required this.label, required this.field});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: Color(0xFF1F2937),
            fontWeight: FontWeight.w700,
            fontSize: 13.5,
          ),
        ),
        const SizedBox(height: 6),
        field,
      ],
    );
  }
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
          disabledBackgroundColor: AuthSplitShell.maroon.withValues(
            alpha: 0.65,
          ),
          elevation: 0,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        child:
            loading
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
                    fontWeight: FontWeight.w700,
                    fontSize: 15,
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
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        child: Text(
          label,
          style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
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
