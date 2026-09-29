import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../app_route_observer.dart';
import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../navigation/soft_page_route.dart';
import '../services/api_client.dart';
import '../widgets/public_site_header.dart';
import 'chatbot_page.dart';
import 'knowledge_base_page.dart';
import 'my_tickets_page.dart';

/// Shared max content width for the hero and Resources sections so the
/// homepage reads as one wide, intentional composition on desktop instead
/// of a narrow column floating in unused whitespace. A max-width cap, not a
/// fixed width, so it still shrinks naturally on narrower viewports.
const double kHomeContentMaxWidth = 1320;

/// Public ASKa-Piyu landing page (no sidebar) — matches the branded site mock.
class StudentHomePage extends StatefulWidget {
  const StudentHomePage({super.key});

  @override
  State<StudentHomePage> createState() => _StudentHomePageState();
}

class _StudentHomePageState extends State<StudentHomePage> with RouteAware {
  bool _loading = true;
  bool _loadInFlight = false;
  String? _error;
  List<_LandingCategory> _categories = const [];
  List<_LandingArticle> _articles = const [];
  String _quickTab = 'Common topics';
  String? _lastAuthKey;
  ModalRoute<dynamic>? _route;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route != _route) {
      appRouteObserver.unsubscribe(this);
      _route = route;
      if (route is PageRoute) {
        appRouteObserver.subscribe(this, route);
      }
    }
    // Reload when auth role changes (e.g. faculty login/logout) so public
    // student KB is not stuck on an empty faculty-audience result set.
    final auth = AuthScope.of(context);
    final authKey = '${auth.isAuthenticated}:${auth.role ?? ''}';
    if (_lastAuthKey != authKey) {
      _lastAuthKey = authKey;
      _loadPublicKb();
    }
  }

  @override
  void dispose() {
    appRouteObserver.unsubscribe(this);
    super.dispose();
  }

  @override
  void didPopNext() {
    // Returning from admin / KB after publishing — refresh counts.
    _loadPublicKb();
  }

  Future<void> _loadPublicKb() async {
    if (_loadInFlight) return;
    _loadInFlight = true;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final authHeaders = AuthScope.of(context).ticketHeaders();
      final categoriesData = await _getJson(
        '/kb/categories',
        headers: authHeaders,
      );
      final articlesData = await _getJson(
        '/kb/articles?limit=100',
        headers: authHeaders,
      );
      final categoryItems =
          categoriesData['items'] is List
              ? categoriesData['items'] as List
              : const [];
      final articleItems =
          articlesData['items'] is List
              ? articlesData['items'] as List
              : const [];
      if (!mounted) return;
      setState(() {
        _categories =
            categoryItems
                .whereType<Map>()
                .map(
                  (item) => _LandingCategory.fromJson(
                    Map<String, dynamic>.from(item),
                  ),
                )
                .where((item) => item.name.isNotEmpty)
                .toList();
        _articles =
            articleItems
                .whereType<Map>()
                .map(
                  (item) => _LandingArticle.fromJson(
                    Map<String, dynamic>.from(item),
                  ),
                )
                .toList();
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not load published Knowledge Base content.';
        _loading = false;
      });
    } finally {
      _loadInFlight = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final isNarrow = width < 880;

    return Scaffold(
      backgroundColor: Colors.white,
      body: Stack(
        children: [
          RefreshIndicator(
            color: DesignTokens.maroon,
            onRefresh: _loadPublicKb,
            child: CustomScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              slivers: [
                // The navbar now lives INSIDE _HeroSection's own Stack
                // (as the first item of its sizing column) instead of a
                // separate preceding sliver -- see _HeroSectionState.build.
                // That is what lets the decorative top wave paint as one
                // continuous page-level layer behind both the navbar and
                // the upper hero, instead of being trapped inside a Stack
                // sized to the navbar's own ~80px box (which is why it
                // used to read as flat horizontal strips no matter how the
                // curve's control points changed).
                SliverToBoxAdapter(child: _HeroSection(isNarrow: isNarrow)),
                SliverToBoxAdapter(
                  child: Center(
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: kHomeContentMaxWidth),
                      child: Padding(
                        padding: EdgeInsets.fromLTRB(
                          isNarrow ? 18 : 32,
                          8,
                          isNarrow ? 18 : 32,
                          100,
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.center,
                              children: [
                                Text(
                                  'Resources',
                                  style: TextStyle(
                                    fontSize: isNarrow ? 24 : 32,
                                    fontWeight: FontWeight.w900,
                                    color: DesignTokens.ink,
                                  ),
                                ),
                                const Spacer(),
                                if (_categories.isNotEmpty)
                                  _SeeAllPill(
                                    label:
                                        isNarrow
                                            ? 'See all'
                                            : 'See all categories',
                                    onTap:
                                        () => softPush(
                                          context,
                                          const KnowledgeBasePage(),
                                        ),
                                  ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Text(
                              'Browse guides, policies, forms, and procedures '
                              'for students, faculty, and staff.',
                              style: TextStyle(
                                color: DesignTokens.muted,
                                fontSize: isNarrow ? 13.5 : 15,
                                height: 1.4,
                              ),
                            ),
                            const SizedBox(height: 22),
                            if (_loading)
                              const Padding(
                                padding: EdgeInsets.symmetric(vertical: 40),
                                child: Center(
                                  child: CircularProgressIndicator(),
                                ),
                              )
                            else if (_error != null)
                              Text(
                                _error!,
                                style: const TextStyle(
                                  color: DesignTokens.muted,
                                ),
                              )
                            else if (_categories.isEmpty)
                              Text(
                                AuthScope.of(context).role == 'faculty'
                                    ? 'No faculty Knowledge Base articles published yet. Ask an admin to publish Faculty Manual topics for faculty.'
                                    : 'No published Knowledge Base categories yet.',
                                style: const TextStyle(
                                  color: DesignTokens.muted,
                                ),
                              )
                            else
                              _ResourcesGrid(
                                categories: _categories,
                                isNarrow: isNarrow,
                              ),
                            const SizedBox(height: 42),
                            Text(
                              'Quick links',
                              style: TextStyle(
                                fontSize: isNarrow ? 22 : 28,
                                fontWeight: FontWeight.w900,
                                color: DesignTokens.ink,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Text(
                              'Frequently used guides and university services.',
                              style: TextStyle(
                                color: DesignTokens.muted,
                                fontSize: isNarrow ? 13.5 : 15,
                                height: 1.4,
                              ),
                            ),
                            const SizedBox(height: 22),
                            if (!_loading && _error == null)
                              _QuickLinksSection(
                                isNarrow: isNarrow,
                                selectedTab: _quickTab,
                                onTabChanged: (tab) =>
                                    setState(() => _quickTab = tab),
                                categories: _categories,
                                articles: _articles,
                              ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          Positioned(
            right: 20,
            bottom: 20,
            child: _FloatingChatButton(
              compact: isNarrow,
              onTap: () => softPush(context, const ChatbotPage()),
            ),
          ),
        ],
      ),
    );
  }
}

/// Large, translucent, organic blush shape flowing behind the navbar's
/// ASKa-Piyu brand mark -- purely decorative, painted behind the header
/// content (see the Stack in [_StudentHomePageState.build]). Confined to
/// the far upper-left and tapering to nothing well before the nav links, so
/// it never competes with navigation/reading content. Several slim contour
/// strokes echo the same flow at a lower alpha, per the approved reference.
///
/// The FILL is built from two independently-curved boundary paths (a top
/// edge and a bottom edge, each its own short cubic-Bezier chain) that only
/// ever meet at the shape's two endpoints -- never a single long chain of
/// small segments sharing anchors, which is what caused an earlier attempt
/// to pinch into a visible gap/hole. A horizontal alpha-gradient shader
/// fades the fill (and every contour stroke) out by ~42-58% width, well
/// before the right-side nav links, instead of an abrupt geometric cutoff.
/// Every curve swings through a large fraction of the painter's own height
/// (not a shallow dip), so the curvature reads as genuine organic motion
/// even in a short, wide navbar box, instead of a flat horizontal strip.
class _TopBrandWavePainter extends CustomPainter {
  const _TopBrandWavePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // Full-strength color from x=0 out to `holdFraction`, then a linear
    // fade down to zero alpha by `fadeEndFraction` -- used for the thin
    // contour strokes, which should simply be strongest at the corner and
    // taper away.
    ui.Gradient fadeShader(
      Color color, {
      required double holdFraction,
      required double fadeEndFraction,
    }) {
      final holdStop = (holdFraction / fadeEndFraction).clamp(0.0, 1.0);
      return ui.Gradient.linear(
        const Offset(0, 0),
        Offset(w * fadeEndFraction, 0),
        [color, color, color.withValues(alpha: 0)],
        [0.0, holdStop, 1.0],
      );
    }

    // Three GEOMETRICALLY INDEPENDENT closed ribbon paths -- not one big
    // fill recolored in bands. Each has its own top/bottom boundary curves,
    // its own vertical band, and its own horizontal reach, so their
    // silhouettes only partially coincide: some areas are covered by one
    // ribbon, some by two overlapping, and some by none at all (real pale
    // negative space showing the page background through), which is what a
    // single shared outline could never produce no matter how its fill
    // color/alpha was varied.

    // Ribbon 1 -- upper flow: thin, pale, enters just outside the top-left
    // corner and curves directly behind/around the brand mark before
    // tapering by ~30% width.
    final ribbon1 = Path()
      ..moveTo(-w * 0.06, -h * 0.03)
      ..cubicTo(w * 0.02, h * 0.02, w * 0.08, -h * 0.02, w * 0.16, h * 0.08)
      ..cubicTo(w * 0.22, h * 0.14, w * 0.26, h * 0.22, w * 0.30, h * 0.20)
      ..cubicTo(w * 0.26, h * 0.34, w * 0.20, h * 0.38, w * 0.14, h * 0.30)
      ..cubicTo(w * 0.08, h * 0.24, w * 0.00, h * 0.20, -w * 0.06, h * 0.14)
      ..close();
    canvas.drawPath(
      ribbon1,
      Paint()..shader = fadeShader(
        const Color(0xFFF6DEE0).withValues(alpha: 0.68),
        holdFraction: 0.05,
        fadeEndFraction: 0.30,
      ),
    );

    // Ribbon 2 -- main flow: the broadest, most visible ribbon, entering
    // outside the left edge and sweeping down past the brand mark before
    // tapering by ~40% width. Overlaps ribbon 1 only around the brand area
    // (its own top boundary crosses through ribbon 1's lower half there);
    // everywhere else it occupies fresh vertical space ribbon 1 never
    // reaches, and leaves the band between ~0.38h-0.55h at the far left
    // (x<0.05w) as visible pale gap.
    final ribbon2 = Path()
      ..moveTo(-w * 0.06, h * 0.22)
      ..cubicTo(w * 0.04, h * 0.10, w * 0.14, h * 0.30, w * 0.22, h * 0.42)
      ..cubicTo(w * 0.30, h * 0.52, w * 0.34, h * 0.60, w * 0.40, h * 0.55)
      ..cubicTo(w * 0.34, h * 0.78, w * 0.24, h * 0.85, w * 0.14, h * 0.78)
      ..cubicTo(w * 0.06, h * 0.72, -w * 0.02, h * 0.62, -w * 0.06, h * 0.55)
      ..close();
    canvas.drawPath(
      ribbon2,
      Paint()..shader = fadeShader(
        const Color(0xFFEFCAD0).withValues(alpha: 0.60),
        holdFraction: 0.06,
        fadeEndFraction: 0.40,
      ),
    );

    // Ribbon 3 -- secondary dusty-rose accent: narrower, concentrated in
    // the upper-left, tapering earliest (~24% width) of the three. Partly
    // overlaps ribbons 1 and 2 in the brand-mark zone for real depth, but
    // its own boundary is independent, so it also covers a small sliver
    // neither of the others reaches.
    final ribbon3 = Path()
      ..moveTo(-w * 0.04, h * 0.38)
      ..cubicTo(w * 0.02, h * 0.30, w * 0.08, h * 0.48, w * 0.14, h * 0.40)
      ..cubicTo(w * 0.19, h * 0.34, w * 0.22, h * 0.42, w * 0.24, h * 0.50)
      ..cubicTo(w * 0.18, h * 0.62, w * 0.10, h * 0.66, w * 0.04, h * 0.60)
      ..cubicTo(-w * 0.01, h * 0.56, -w * 0.04, h * 0.50, -w * 0.04, h * 0.46)
      ..close();
    canvas.drawPath(
      ribbon3,
      Paint()..shader = fadeShader(
        const Color(0xFFD8A4A9).withValues(alpha: 0.50),
        holdFraction: 0.04,
        fadeEndFraction: 0.24,
      ),
    );

    // Four slim contour lines echoing the same corner-hugging, steeply
    // descending flow, each its own distinct Bezier path (different start
    // height, control points, and fade reach) so they read as organic,
    // non-parallel companions to the fill -- essentially gone by ~34-40%
    // width, short of where the fill itself fades.
    void drawContour(
      Path path, {
      required Color color,
      required double w0,
      required double holdFraction,
      required double fadeEndFraction,
    }) {
      canvas.drawPath(
        path,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = w0
          ..strokeCap = StrokeCap.round
          ..shader = fadeShader(
            color,
            holdFraction: holdFraction,
            fadeEndFraction: fadeEndFraction,
          ),
      );
    }

    drawContour(
      Path()
        ..moveTo(-w * 0.04, -h * 0.02)
        ..cubicTo(w * 0.05, h * 0.35, w * 0.12, -h * 0.10, w * 0.18, h * 0.22)
        ..cubicTo(w * 0.24, h * 0.50, w * 0.28, h * 0.75, w * 0.34, h * 0.62),
      color: const Color(0xFFB05A61).withValues(alpha: 0.40),
      w0: 1.4,
      holdFraction: 0.16,
      fadeEndFraction: 0.36,
    );
    drawContour(
      Path()
        ..moveTo(-w * 0.04, h * 0.15)
        ..cubicTo(w * 0.03, h * 0.75, w * 0.10, -h * 0.05, w * 0.16, h * 0.42)
        ..cubicTo(w * 0.22, h * 0.68, w * 0.27, h * 0.30, w * 0.32, h * 0.50),
      color: const Color(0xFFD79AA0).withValues(alpha: 0.40),
      w0: 1.2,
      holdFraction: 0.14,
      fadeEndFraction: 0.34,
    );
    drawContour(
      Path()
        ..moveTo(-w * 0.03, h * 0.35)
        ..cubicTo(w * 0.05, h * 0.90, w * 0.13, h * 0.15, w * 0.20, h * 0.62)
        ..cubicTo(w * 0.26, h * 0.85, w * 0.30, h * 0.55, w * 0.36, h * 0.70),
      color: const Color(0xFFB05A61).withValues(alpha: 0.36),
      w0: 1.1,
      holdFraction: 0.18,
      fadeEndFraction: 0.38,
    );
    drawContour(
      Path()
        ..moveTo(-w * 0.02, h * 0.55)
        ..cubicTo(w * 0.04, h * 0.20, w * 0.11, h * 0.85, w * 0.17, h * 0.48)
        ..cubicTo(w * 0.22, h * 0.30, w * 0.27, h * 0.62, w * 0.33, h * 0.45),
      color: const Color(0xFFD79AA0).withValues(alpha: 0.34),
      w0: 1.0,
      holdFraction: 0.15,
      fadeEndFraction: 0.35,
    );
  }

  @override
  bool shouldRepaint(covariant _TopBrandWavePainter oldDelegate) => false;
}

class _HeroSection extends StatefulWidget {
  final bool isNarrow;

  const _HeroSection({required this.isNarrow});

  @override
  State<_HeroSection> createState() => _HeroSectionState();
}

class _HeroSectionState extends State<_HeroSection> {
  final TextEditingController _searchCtrl = TextEditingController();

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  void _search() {
    final query = _searchCtrl.text.trim();
    softPush(context, KnowledgeBasePage(initialQuery: query));
  }

  @override
  Widget build(BuildContext context) {
    final isNarrow = widget.isNarrow;
    final subtitle =
        AuthScope.of(context).role == 'faculty'
            ? 'Find faculty support articles, procedures, and answers\nfor Laguna State Polytechnic University.'
            : 'Find student support articles, procedures, and answers\nfor Laguna State Polytechnic University.';

    final heading = ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 720),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            'LAGUNA STATE POLYTECHNIC UNIVERSITY',
            style: TextStyle(
              color: DesignTokens.muted,
              fontWeight: FontWeight.w700,
              fontSize: isNarrow ? 12 : 13,
              letterSpacing: 1.6,
            ),
          ),
          SizedBox(height: isNarrow ? 8 : 16),
          RichText(
            text: TextSpan(
              style: TextStyle(
                fontWeight: FontWeight.w900,
                fontSize: isNarrow ? 32 : 52,
                height: 1.1,
                letterSpacing: -0.5,
              ),
              children: [
                const TextSpan(
                  text: 'Welcome to ',
                  style: TextStyle(color: DesignTokens.ink),
                ),
                TextSpan(
                  // U+2011 non-breaking hyphen: "ASKa-Piyu" must never
                  // split at the hyphen; if the line wraps at all, it
                  // wraps at the space before this span instead.
                  text: 'ASKa‑Piyu',
                  style: TextStyle(color: DesignTokens.maroon),
                ),
              ],
            ),
          ),
          SizedBox(height: isNarrow ? 10 : 18),
          Text(
            subtitle,
            style: TextStyle(
              color: DesignTokens.muted,
              fontSize: isNarrow ? 13.5 : 17,
              height: 1.4,
            ),
          ),
        ],
      ),
    );

    final searchBar = ConstrainedBox(
      constraints: BoxConstraints(maxWidth: isNarrow ? double.infinity : 860),
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: const Color(0xFFE5E7EB)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.07),
              blurRadius: 22,
              offset: const Offset(0, 10),
            ),
          ],
        ),
        child: Row(
          children: [
            SizedBox(width: isNarrow ? 10 : 18),
            // Leading search icon -- mobile only (see the approved mobile
            // reference); the desktop bar has never had one and stays
            // exactly as before.
            if (isNarrow) ...[
              const Icon(
                Icons.search_rounded,
                color: DesignTokens.maroon,
                size: 20,
              ),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: TextField(
                controller: _searchCtrl,
                onSubmitted: (_) => _search(),
                style: TextStyle(fontSize: isNarrow ? 14 : 16),
                decoration: InputDecoration(
                  hintText:
                      'Search articles, policies, offices, or procedures...',
                  border: InputBorder.none,
                  isDense: true,
                  hintStyle: TextStyle(
                    color: const Color(0xFF9CA3AF),
                    fontSize: isNarrow ? 14 : 16,
                  ),
                ),
              ),
            ),
            SizedBox(width: isNarrow ? 8 : 10),
            SizedBox(
              height: isNarrow ? 44 : 56,
              child: ElevatedButton(
                onPressed: _search,
                style: ElevatedButton.styleFrom(
                  backgroundColor: DesignTokens.maroon,
                  foregroundColor: Colors.white,
                  elevation: 0,
                  padding: EdgeInsets.symmetric(
                    horizontal: isNarrow ? 16 : 30,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(13),
                  ),
                ),
                child: Text(
                  'Search',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: isNarrow ? 14 : 16,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );

    final foreground = Container(
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(
        isNarrow ? 18 : 32,
        isNarrow ? 20 : 68,
        isNarrow ? 18 : 32,
        isNarrow ? 28 : 88,
      ),
      // Content alone drives the hero's height -- the building photo never
      // does. Text + search dominate the hierarchy; the photo and waves
      // are supporting elements layered behind/around this natural height.
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [heading, SizedBox(height: isNarrow ? 16 : 30), searchBar],
      ),
    );

    // LayoutBuilder hoisted ABOVE the Stack: a Positioned returned from a
    // LayoutBuilder that is itself a child of Stack is not recognized as a
    // direct positioned child of that Stack -- a real Flutter pitfall, not
    // a style preference -- it throws at runtime instead of laying out.
    return LayoutBuilder(
      builder: (context, constraints) {
        final heroWidth = constraints.maxWidth;
        return Stack(
          // Loose fit: the Stack sizes itself to `foreground` (its one
          // non-positioned child), never to the building photo, so the
          // photo can never determine hero height.
          children: [
            // A visibly (if elegantly) pale maroon/blush wash across the
            // WHOLE hero -- deliberately never touching pure white at any
            // stop, so the hero reads as a distinct soft blush band
            // between the pure-white navbar above and the pure-white
            // Resources section below. An earlier attempt started this
            // gradient at pure white, which made the text-heavy upper
            // portion of the hero look plain white next to the Resources
            // section -- too subtle to notice. These three stops are all
            // pale blush tones (never white), so the whole hero carries a
            // consistent, gentle warmth from top to bottom.
            Positioned.fill(
              child: IgnorePointer(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: const [
                        Color(0xFFFFF5F6),
                        Color(0xFFFDF1F2),
                        Color(0xFFFCEFF1),
                      ],
                      stops: const [0.0, 0.5, 1.0],
                    ),
                  ),
                ),
              ),
            ),
            // Page-level decorative top wave: a tall canvas (not clipped to
            // the navbar's own ~80px box) anchored to this Stack's y=0,
            // which is now the TRUE top of the page since the navbar is
            // the first item of `foreground` below rather than a separate
            // preceding sliver. This is what lets the ribbon have a real,
            // large downward sweep instead of being squashed into a flat
            // strip. It paints on top of the pale gradient above but
            // behind the building/bottom-waves/navbar+hero content below.
            Positioned(
              top: 0,
              left: 0,
              right: 0,
              height: isNarrow ? 130 : 180,
              child: IgnorePointer(
                child: CustomPaint(painter: _TopBrandWavePainter()),
              ),
            ),
            if (!isNarrow)
              Positioned(
                top: 0,
                bottom: 0,
                right: 0,
                width: heroWidth * 0.46,
                // Behind the text/search content entirely -- content is
                // free to sit over its faded portion because this layer
                // never claims hit-testing priority or visual weight.
                child: IgnorePointer(
                  child: Opacity(
                    opacity: 0.90,
                    child: ClipRect(
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          Image.asset(
                            'assets/images/lspu_admin_building.png',
                            fit: BoxFit.cover,
                            alignment: Alignment.center,
                            filterQuality: FilterQuality.high,
                          ),
                          // Left-to-right fade only -- the building reads
                          // as almost fully blended at the left edge, then
                          // grows steadily clearer, so the LSPU lettering,
                          // flag, facade, and signage are strongly visible
                          // by the right third. Tinted to the same blush
                          // as the new hero background (not pure white) so
                          // the building's faded left edge blends into it
                          // rather than leaving a mismatched white patch.
                          const DecoratedBox(
                            decoration: BoxDecoration(
                              gradient: LinearGradient(
                                begin: Alignment.centerLeft,
                                end: Alignment.centerRight,
                                colors: [
                                  Color(0xFFFFF5F6),
                                  Color(0x99FFF5F6),
                                  Color(0x33FFF5F6),
                                  Color(0x00FFF5F6),
                                ],
                                stops: [0.0, 0.28, 0.48, 0.68],
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            // Mobile-only: the same right-anchored, left-to-right-fading
            // building panel as desktop (not a short bottom band), just at
            // a mobile-appropriate width fraction. This is what keeps the
            // building genuinely visible in the background toward the
            // right of the hero -- matching the approved mobile reference
            // -- while the fade still keeps the left/center text area
            // fully readable, exactly like the desktop treatment.
            if (isNarrow)
              Positioned(
                top: 0,
                bottom: 0,
                right: 0,
                width: heroWidth * 0.52,
                child: IgnorePointer(
                  child: Opacity(
                    opacity: 0.55,
                    child: ClipRect(
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          Image.asset(
                            'assets/images/lspu_admin_building.png',
                            fit: BoxFit.cover,
                            alignment: Alignment.center,
                            filterQuality: FilterQuality.high,
                          ),
                          // Fade pushed further right than the desktop
                          // panel's own stops -- at mobile widths the
                          // "LAGUNA STATE POLYTECHNIC UNIVERSITY" label
                          // spans nearly the full text column, so the pale
                          // coverage needs to reach almost to the panel's
                          // own right edge to keep that line clear of the
                          // building's more solid roofline/sky detail.
                          const DecoratedBox(
                            decoration: BoxDecoration(
                              gradient: LinearGradient(
                                begin: Alignment.centerLeft,
                                end: Alignment.centerRight,
                                colors: [
                                  Color(0xFFFFF5F6),
                                  Color(0x99FFF5F6),
                                  Color(0x40FFF5F6),
                                  Color(0x00FFF5F6),
                                ],
                                stops: [0.0, 0.42, 0.68, 0.90],
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            // Decorative wave artwork sits BEHIND the text/search content
            // (painted before `foreground` below) so its color can never
            // obscure the content, which always paints on top of it. The
            // canvas spans the full hero so the painter's own anchor
            // points -- not the container size -- control how much of the
            // hero the waves actually occupy (kept to roughly the lower
            // third; see _HeroWaveFullPainter).
            if (!isNarrow)
              const Positioned.fill(
                child: IgnorePointer(
                  child: CustomPaint(painter: _HeroWaveFullPainter()),
                ),
              )
            else
              Positioned(
                left: 0,
                right: 0,
                bottom: -1,
                child: IgnorePointer(
                  child: SizedBox(
                    height: 64,
                    width: double.infinity,
                    child: const CustomPaint(painter: _HeroWavePainter()),
                  ),
                ),
              ),
            // Navbar is the first item of the Stack's one non-positioned
            // sizing child (a Column), not a separate sliver -- this is
            // what lets the decorative wave above paint as one continuous
            // page-level layer behind both the navbar and the hero, while
            // the navbar itself keeps its exact original padding/height
            // and stays the topmost (clickable) layer. `slim: isNarrow`
            // reuses PublicSiteHeader's own existing compact-header
            // support (smaller logo + tighter vertical padding) to trim
            // unnecessary mobile header height, without touching the
            // shared header's code or its appearance on any other page.
            Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                PublicSiteHeader(
                  transparentBackground: true,
                  slim: isNarrow,
                ),
                foreground,
              ],
            ),
          ],
        );
      },
    );
  }
}

/// A deliberate, flowing wave motif for the hero's bottom edge -- a real
/// ASKa-Piyu brand element, not a thin separator. Three layers (pale pink,
/// muted maroon, deep maroon), each built from just 4 large anchor points
/// (crest/valley/crest/ending) spanning the FULL hero width -- including
/// the portion under the building photo, where a visible secondary crest
/// keeps the curve energetic rather than flattening out. Anchors are
/// joined with a Catmull-Rom-derived cubic spline (a small number of large,
/// smooth curves) rather than many small points, so the undulation reads
/// clearly at 1600px instead of looking like near-parallel stripes. The
/// deep layer's crests stay well below the pale layer's everywhere, so it
/// never approaches the search bar above.
class _HeroWavePainter extends CustomPainter {
  const _HeroWavePainter();

  @override
  void paint(Canvas canvas, Size size) {
    // Pale pink: broadest reach, may rise closest to the search bar.
    // Anchors (x-fraction, topY-fraction): start moderately high, descend
    // into a broad valley, rise into a second crest under the building,
    // then a soft ending into the Resources boundary.
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFFE9C6CB).withValues(alpha: 0.60),
      anchors: const [
        Offset(0.0, 0.40),
        Offset(0.30, 0.80),
        Offset(0.62, 0.30),
        Offset(1.0, 0.58),
      ],
    );
    // Muted maroon/rose: its own distinct crest/valley positions (not the
    // pale curve offset downward) so the overlap band varies in
    // thickness, with its own secondary crest further right, under the
    // building.
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFFB05A61).withValues(alpha: 0.68),
      anchors: const [
        Offset(0.0, 0.58),
        Offset(0.34, 0.74),
        Offset(0.68, 0.40),
        Offset(1.0, 0.66),
      ],
    );
    // Deep maroon: the layer needing the most visible top-edge motion --
    // moderately thick on the left, thinning toward the center, then a
    // clear secondary rise beneath the building before settling to a
    // medium depth at the right edge. Its highest point (0.48) is capped
    // well below the pale/medium layers' reach, so it stays substantially
    // clear of the search bar in every case.
    _paintLayer(
      canvas,
      size,
      color: DesignTokens.maroon.withValues(alpha: 0.90),
      anchors: const [
        Offset(0.0, 0.62),
        Offset(0.26, 0.55),
        Offset(0.52, 0.80),
        Offset(0.80, 0.48),
        Offset(1.0, 0.62),
      ],
    );
  }

  /// Builds one large, smooth wave through a small set of (x-fraction,
  /// topY-fraction) anchor points using a Catmull-Rom-to-cubic-Bezier
  /// conversion -- a handful of big, deliberate curve segments rather than
  /// many tiny ones, so each crest/valley is visually obvious at full
  /// hero width.
  void _paintLayer(
    Canvas canvas,
    Size size, {
    required Color color,
    required List<Offset> anchors,
  }) {
    final pts = <Offset>[
      for (final a in anchors) Offset(size.width * a.dx, size.height * a.dy),
    ];

    final path = Path()..moveTo(0, size.height)..lineTo(pts.first.dx, pts.first.dy);
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
  bool shouldRepaint(covariant _HeroWavePainter oldDelegate) => false;
}

/// Desktop wave artwork: large, translucent, crossing layers spanning the
/// hero's FULL size (not a thin bottom strip) so the composition reads as
/// an integrated brand element behind the text/search/building rather than
/// a footer. Each layer is defined by a handful of widely-spaced anchor
/// points -- (x-fraction, topY-fraction of the ENTIRE hero) -- joined by
/// the same Catmull-Rom-derived cubic spline used by [_HeroWavePainter].
/// Unlike an earlier, oversized revision of this painter, every anchor is
/// deliberately kept low (mostly y >= 0.58 of the full hero height, i.e.
/// confined to roughly the lower third) so the waves read as secondary
/// decoration -- only the pale layer's leftmost point is allowed to sit
/// higher, and even then it stays subtle (low alpha). This painter is
/// only ever placed behind `foreground` in the hero Stack, so it can
/// never reduce legibility of the text/search above it.
class _HeroWaveFullPainter extends CustomPainter {
  const _HeroWaveFullPainter();

  @override
  void paint(Canvas canvas, Size size) {
    // Pale pink: the only layer allowed to begin relatively high on the
    // far left; otherwise stays low, with a broad, shallow undulation
    // across the middle and right -- no large crest under the building.
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFFE9C6CB).withValues(alpha: 0.40),
      anchors: const [
        Offset(0.00, 0.43),
        Offset(0.18, 0.72),
        Offset(0.38, 0.88),
        Offset(0.55, 0.83),
        Offset(0.72, 0.88),
        Offset(0.88, 0.78),
        Offset(1.00, 0.70),
      ],
    );
    // Muted maroon/rose: begins lower than the pale layer on the left and
    // stays low across the whole width, including under the building --
    // no tall secondary crest.
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFFB05A61).withValues(alpha: 0.42),
      anchors: const [
        Offset(0.00, 0.58),
        Offset(0.20, 0.82),
        Offset(0.38, 0.94),
        Offset(0.55, 0.88),
        Offset(0.72, 0.96),
        Offset(0.88, 0.86),
        Offset(1.00, 0.80),
      ],
    );
    // Deep maroon: the strongest-hued but still translucent layer, kept
    // substantially lower than the other two everywhere so it never
    // crowds the search area and never becomes a wide, tall block.
    _paintLayer(
      canvas,
      size,
      color: DesignTokens.maroon.withValues(alpha: 0.52),
      anchors: const [
        Offset(0.00, 0.70),
        Offset(0.20, 0.90),
        Offset(0.38, 0.98),
        Offset(0.55, 0.94),
        Offset(0.72, 0.99),
        Offset(0.88, 0.92),
        Offset(1.00, 0.86),
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

    final path = Path()..moveTo(0, size.height)..lineTo(pts.first.dx, pts.first.dy);
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
  bool shouldRepaint(covariant _HeroWaveFullPainter oldDelegate) => false;
}

/// Pale-blush pill button used for the Resources section's "See all
/// categories" link, replacing the previous icon-led text link -- keeps the
/// single "browse everything" entry point but matches the approved
/// reference's placement (upper-right of the section header) and styling,
/// without adding a decorative icon (only the small chevron, already on the
/// allowed list).
class _SeeAllPill extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const _SeeAllPill({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xFFFCE8EA),
      borderRadius: BorderRadius.circular(999),
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label,
                style: const TextStyle(
                  color: DesignTokens.maroon,
                  fontWeight: FontWeight.w800,
                  fontSize: 13.5,
                ),
              ),
              const SizedBox(width: 2),
              const Icon(
                Icons.chevron_right_rounded,
                size: 18,
                color: DesignTokens.maroon,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ResourcesGrid extends StatelessWidget {
  final List<_LandingCategory> categories;
  final bool isNarrow;

  const _ResourcesGrid({required this.categories, required this.isNarrow});

  @override
  Widget build(BuildContext context) {
    final columns =
        isNarrow
            ? 2
            : MediaQuery.sizeOf(context).width >= 1000
            ? 3
            : 2;
    final shown = categories;

    return LayoutBuilder(
      builder: (context, constraints) {
        final gap = isNarrow ? 8.0 : 16.0;
        final cardWidth =
            (constraints.maxWidth - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children:
              shown.map((category) {
                return SizedBox(
                  width: cardWidth,
                  child: Material(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(14),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(14),
                      onTap:
                          () => softPush(
                            context,
                            KnowledgeBasePage(initialCategory: category.name),
                          ),
                      child: Container(
                        constraints: BoxConstraints(
                          minHeight: isNarrow ? 76 : 140,
                        ),
                        // A single BoxDecoration cannot combine a
                        // borderRadius with a Border whose sides have
                        // different colors -- Flutter throws "A
                        // borderRadius can only be given on borders with
                        // uniform colors" at paint time, which silently
                        // fails to paint this box (while InkWell/Material
                        // above still handle hit-testing, so the card stays
                        // clickable but invisible). The outer border here
                        // is therefore uniform; the pink accent is a
                        // separate clipped layer below, not a differently
                        // colored BorderSide.
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: const Color(0xFFE5E7EB)),
                        ),
                        clipBehavior: Clip.antiAlias,
                        child: Stack(
                          children: [
                            // Pink accent strip -- clipped to the card's
                            // rounded rect by the Container's clipBehavior
                            // above, so its corners never poke past the
                            // uniform outer border.
                            const Positioned(
                              left: 0,
                              top: 0,
                              bottom: 0,
                              width: 4,
                              child: ColoredBox(color: Color(0xFFE8B4B8)),
                            ),
                            Padding(
                              // Left padding carries the extra 4px the
                              // accent strip used to occupy as part of the
                              // old (broken) left BorderSide's width, so
                              // the text content lines up exactly as
                              // before.
                              padding: EdgeInsets.fromLTRB(
                                (isNarrow ? 12 : 24) + 4,
                                isNarrow ? 12 : 24,
                                isNarrow ? 12 : 24,
                                isNarrow ? 12 : 24,
                              ),
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          category.name,
                                          style: TextStyle(
                                            color: DesignTokens.maroon,
                                            fontWeight: FontWeight.w900,
                                            fontSize: isNarrow ? 14 : 17,
                                          ),
                                        ),
                                        const SizedBox(height: 6),
                                        Text(
                                          category.articleCount > 0
                                              ? '${category.articleCount} article${category.articleCount == 1 ? '' : 's'}'
                                              : 'Browse articles',
                                          maxLines: 2,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(
                                            color: Color(0xFF4B5563),
                                            height: 1.4,
                                            fontSize: isNarrow ? 12 : 14,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  Icon(
                                    Icons.chevron_right_rounded,
                                    size: isNarrow ? 18 : 20,
                                    color: DesignTokens.maroon,
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                );
              }).toList(),
        );
      },
    );
  }
}

/// Horizontal-tab + responsive card-grid presentation of Quick Links.
/// Groups are built from the SAME real `/kb/categories` + `/kb/articles`
/// data already used by the Resources section above -- no fabricated
/// titles, counts, or shortcuts.
class _QuickLinksSection extends StatelessWidget {
  final bool isNarrow;
  final String selectedTab;
  final ValueChanged<String> onTabChanged;
  final List<_LandingCategory> categories;
  final List<_LandingArticle> articles;

  const _QuickLinksSection({
    required this.isNarrow,
    required this.selectedTab,
    required this.onTabChanged,
    required this.categories,
    required this.articles,
  });

  static const tabs = [
    'Common topics',
    'Role-based guides',
    'Additional resources',
  ];

  /// Real published categories, each paired with up to 3 real article
  /// titles drawn from the same category (via `_LandingArticle.category`)
  /// and an accurate remaining count. A category is only rendered if at
  /// least one of its real articles was actually returned.
  List<_QuickLinkGroup> _groupByCategory() {
    final byCategory = <String, List<String>>{};
    for (final article in articles) {
      final category = article.category.trim();
      if (category.isEmpty) continue;
      (byCategory[category] ??= <String>[]).add(article.title);
    }
    final groups = <_QuickLinkGroup>[];
    for (final category in categories) {
      final titles = byCategory[category.name];
      if (titles == null || titles.isEmpty) continue;
      groups.add(
        _QuickLinkGroup(
          title: category.name,
          previewTitles: titles.take(3).toList(),
          moreCount: titles.length > 3 ? titles.length - 3 : 0,
          category: category.name,
        ),
      );
    }
    return groups;
  }

  List<_QuickLinkGroup> _buildGroups() {
    if (selectedTab == 'Additional resources') {
      // Real, fixed utility destinations -- not category data, so these
      // render as single-action cards with a short description instead of
      // an article-preview list.
      return const [
        _QuickLinkGroup(
          title: 'Browse Knowledge Base',
          subtitle: 'Search all published support articles',
        ),
        _QuickLinkGroup(
          title: 'Ask ASKa-Piyu',
          subtitle: 'Chat with the campus assistant',
          openChat: true,
        ),
        _QuickLinkGroup(
          title: 'My Tickets',
          subtitle: 'Track support requests',
          openTickets: true,
        ),
      ];
    }
    if (selectedTab == 'Role-based guides') {
      final byOffice = <String, List<String>>{};
      for (final article in articles) {
        final office = article.office.trim();
        if (office.isEmpty) continue;
        (byOffice[office] ??= <String>[]).add(article.title);
      }
      if (byOffice.isEmpty) {
        // No office-tagged articles published -- fall back to the same
        // real category/article grouping as Common topics rather than
        // showing an empty tab.
        return _groupByCategory();
      }
      final offices = byOffice.keys.toList()..sort();
      return [
        for (final office in offices)
          _QuickLinkGroup(
            title: office,
            previewTitles: byOffice[office]!.take(3).toList(),
            moreCount:
                byOffice[office]!.length > 3 ? byOffice[office]!.length - 3 : 0,
            query: office,
          ),
      ];
    }
    // Common topics.
    return _groupByCategory();
  }

  @override
  Widget build(BuildContext context) {
    final groups = _buildGroups();

    final tabButtons = [
      for (final tab in tabs)
        Material(
          color: tab == selectedTab ? const Color(0xFFFCE8EA) : Colors.white,
          borderRadius: BorderRadius.circular(10),
          child: InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () => onTabChanged(tab),
            child: Container(
              padding: EdgeInsets.symmetric(
                horizontal: isNarrow ? 12 : 16,
                vertical: isNarrow ? 9 : 12,
              ),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: tab == selectedTab
                      ? const Color(0xFFE8B4B8)
                      : const Color(0xFFE5E7EB),
                ),
              ),
              child: Text(
                tab,
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: isNarrow ? 13 : 14,
                  color: tab == selectedTab
                      ? DesignTokens.maroon
                      : const Color(0xFF4B5563),
                ),
              ),
            ),
          ),
        ),
    ];

    // Mobile: a Wrap, not the horizontally-scrolling Row desktop still
    // uses below -- at 390/360px the three real tab labels (unabbreviated,
    // full size) don't fit one row, and a scrolling row left "Additional
    // resources" clipped by the viewport edge unless the user discovered
    // they could scroll it into view. Wrap lets the third tab fall to its
    // own line instead, with every label fully visible.
    final tabBar = isNarrow
        ? Wrap(spacing: 8, runSpacing: 8, children: tabButtons)
        : SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (final button in tabButtons)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: button,
                  ),
              ],
            ),
          );

    final grid = groups.isEmpty
        ? const Padding(
            padding: EdgeInsets.symmetric(vertical: 20),
            child: Text(
              'No published items yet for this section.',
              style: TextStyle(color: DesignTokens.muted),
            ),
          )
        : LayoutBuilder(
            builder: (context, constraints) {
              final columns = isNarrow
                  ? 1
                  : constraints.maxWidth >= 900
                      ? 3
                      : 2;
              final gap = isNarrow ? 12.0 : 16.0;
              final cardWidth =
                  (constraints.maxWidth - gap * (columns - 1)) / columns;
              return Wrap(
                spacing: gap,
                runSpacing: gap,
                children: [
                  for (final group in groups)
                    SizedBox(
                      width: columns == 1 ? constraints.maxWidth : cardWidth,
                      child: _QuickLinkCard(group: group),
                    ),
                ],
              );
            },
          );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [tabBar, const SizedBox(height: 16), grid],
    );
  }
}

/// One real Quick Links group: either a category/office paired with up to
/// 3 of its real article titles, or (Additional resources only) a fixed
/// utility shortcut with a short description instead of previews.
class _QuickLinkGroup {
  final String title;
  final List<String> previewTitles;
  final int moreCount;
  final String? subtitle;
  final String? category;
  final String? query;
  final bool openChat;
  final bool openTickets;

  const _QuickLinkGroup({
    required this.title,
    this.previewTitles = const [],
    this.moreCount = 0,
    this.subtitle,
    this.category,
    this.query,
    this.openChat = false,
    this.openTickets = false,
  });
}

class _QuickLinkCard extends StatelessWidget {
  final _QuickLinkGroup group;

  const _QuickLinkCard({required this.group});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () {
          if (group.openChat) {
            softPush(context, const ChatbotPage());
            return;
          }
          if (group.openTickets) {
            openProtectedPage(
              context,
              builder: (_) => const MyTicketsPage(),
              requireVerifiedEmail: true,
              message: emailVerifyRequiredMessage,
            );
            return;
          }
          softPush(
            context,
            KnowledgeBasePage(
              initialCategory: group.category,
              initialQuery: group.query,
            ),
          );
        },
        child: Container(
          constraints: const BoxConstraints(minHeight: 128),
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFFE5E7EB)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(
                      group.title,
                      style: const TextStyle(
                        color: DesignTokens.maroon,
                        fontWeight: FontWeight.w900,
                        fontSize: 16,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  const Icon(
                    Icons.chevron_right_rounded,
                    color: DesignTokens.maroon,
                    size: 20,
                  ),
                ],
              ),
              if (group.previewTitles.isNotEmpty) ...[
                const SizedBox(height: 10),
                for (final title in group.previewTitles)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: DesignTokens.muted,
                        fontSize: 13.5,
                        height: 1.4,
                      ),
                    ),
                  ),
                if (group.moreCount > 0)
                  Text(
                    '+${group.moreCount} more',
                    style: const TextStyle(
                      color: DesignTokens.maroon,
                      fontWeight: FontWeight.w700,
                      fontSize: 13,
                    ),
                  ),
              ] else if (group.subtitle != null) ...[
                const SizedBox(height: 8),
                Text(
                  group.subtitle!,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 13.5,
                    height: 1.4,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _FloatingChatButton extends StatelessWidget {
  final VoidCallback onTap;
  final bool compact;

  const _FloatingChatButton({required this.onTap, this.compact = false});

  @override
  Widget build(BuildContext context) {
    // Mobile (compact): icon-only circle, not the text pill. Quick Links
    // renders full-width, edge-to-edge cards in a single column, so any
    // fixed bottom-right floating button inevitably sits over some card's
    // right edge while scrolling -- shrinking to the smallest recognizable
    // footprint (a plain circular mark, ~48px, same color/icon/position as
    // before) is the minimal way to stop it from covering a card's title
    // text or chevron, without repositioning or redesigning either the
    // button or Quick Links.
    if (compact) {
      // Tooltip carries the same accessible name the visible text used to
      // provide ("Chat with ASKa-Piyu"), so removing the label for space
      // doesn't remove it for screen readers/long-press hints.
      return Tooltip(
        message: 'Chat with ASKa-Piyu',
        child: Material(
          color: const Color(0xFF5C0A0F),
          shape: const CircleBorder(),
          elevation: 10,
          shadowColor: Colors.black38,
          child: InkWell(
            onTap: onTap,
            customBorder: const CircleBorder(),
            child: Padding(
              padding: const EdgeInsets.all(7),
              child: Container(
                width: 34,
                height: 34,
                decoration: const BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                ),
                padding: const EdgeInsets.all(6),
                child: Image.asset(
                  'assets/logo.png',
                  fit: BoxFit.contain,
                  filterQuality: FilterQuality.high,
                ),
              ),
            ),
          ),
        ),
      );
    }
    return Material(
      color: const Color(0xFF5C0A0F),
      borderRadius: BorderRadius.circular(999),
      elevation: 10,
      shadowColor: Colors.black38,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(999),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 8, 20, 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: const BoxDecoration(
                  color: Colors.white,
                  shape: BoxShape.circle,
                ),
                padding: const EdgeInsets.all(6),
                child: Image.asset(
                  'assets/logo.png',
                  fit: BoxFit.contain,
                  filterQuality: FilterQuality.high,
                ),
              ),
              const SizedBox(width: 12),
              const Text(
                'Chat with ASKa-Piyu',
                style: TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                  fontSize: 15,
                  letterSpacing: -0.1,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _LandingCategory {
  final String name;
  final int articleCount;
  final String description;

  const _LandingCategory({
    required this.name,
    required this.articleCount,
    required this.description,
  });

  factory _LandingCategory.fromJson(Map<String, dynamic> json) {
    final name = (json['name'] ?? '').toString().trim();
    final count =
        json['article_count'] is int
            ? json['article_count'] as int
            : int.tryParse('${json['article_count']}') ?? 0;
    final sample = json['sample_article_titles'] ?? json['sample_titles'];
    String description;
    if (sample is List && sample.isNotEmpty) {
      description = sample.take(2).map((e) => e.toString()).join(' · ');
    } else if (count > 0) {
      description =
          '$count published article${count == 1 ? '' : 's'} you can read now.';
    } else {
      description = 'Browse published support articles in this category.';
    }
    return _LandingCategory(
      name: name,
      articleCount: count,
      description: description,
    );
  }
}

class _LandingArticle {
  final String title;
  final String category;
  final String office;

  const _LandingArticle({
    required this.title,
    required this.category,
    required this.office,
  });

  factory _LandingArticle.fromJson(Map<String, dynamic> json) {
    return _LandingArticle(
      title: (json['title'] ?? 'Untitled article').toString(),
      category: (json['category'] ?? '').toString(),
      office: (json['office'] ?? '').toString(),
    );
  }
}

Future<Map<String, dynamic>> _getJson(
  String path, {
  Map<String, String> headers = const {},
}) async {
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}$path',
    headers: headers,
  );
  if (!result.ok) {
    throw StateError('Request failed (${result.statusCode}) for $path');
  }
  return result.jsonObject;
}
