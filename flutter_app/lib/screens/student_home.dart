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
                const SliverToBoxAdapter(child: PublicSiteHeader()),
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
                                if (isNarrow && _categories.isNotEmpty)
                                  TextButton(
                                    onPressed:
                                        () => softPush(
                                          context,
                                          const KnowledgeBasePage(),
                                        ),
                                    child: const Text(
                                      'See all',
                                      style: TextStyle(
                                        fontWeight: FontWeight.w800,
                                      ),
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
                            if (!_loading &&
                                _error == null &&
                                _categories.isNotEmpty &&
                                !isNarrow) ...[
                              const SizedBox(height: 14),
                              Align(
                                alignment: Alignment.centerLeft,
                                child: TextButton.icon(
                                  onPressed:
                                      () => softPush(
                                        context,
                                        const KnowledgeBasePage(),
                                      ),
                                  icon: const Icon(Icons.menu_book_outlined),
                                  label: const Text(
                                    'Browse all categories in Knowledge Base',
                                  ),
                                ),
                              ),
                            ],
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
          const SizedBox(height: 16),
          RichText(
            text: TextSpan(
              style: TextStyle(
                fontWeight: FontWeight.w900,
                fontSize: isNarrow ? 38 : 52,
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
          const SizedBox(height: 18),
          Text(
            subtitle,
            style: TextStyle(
              color: DesignTokens.muted,
              fontSize: isNarrow ? 15 : 17,
              height: 1.5,
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
            const SizedBox(width: 18),
            Expanded(
              child: TextField(
                controller: _searchCtrl,
                onSubmitted: (_) => _search(),
                style: const TextStyle(fontSize: 16),
                decoration: const InputDecoration(
                  hintText:
                      'Search articles, policies, offices, or procedures...',
                  border: InputBorder.none,
                  isDense: true,
                  hintStyle: TextStyle(color: Color(0xFF9CA3AF), fontSize: 16),
                ),
              ),
            ),
            const SizedBox(width: 10),
            SizedBox(
              height: 56,
              child: ElevatedButton(
                onPressed: _search,
                style: ElevatedButton.styleFrom(
                  backgroundColor: DesignTokens.maroon,
                  foregroundColor: Colors.white,
                  elevation: 0,
                  padding: const EdgeInsets.symmetric(horizontal: 30),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(13),
                  ),
                ),
                child: const Text(
                  'Search',
                  style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16),
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
        isNarrow ? 44 : 68,
        isNarrow ? 18 : 32,
        isNarrow ? 72 : 88,
      ),
      // Content alone drives the hero's height -- the building photo never
      // does. Text + search dominate the hierarchy; the photo and waves
      // are supporting elements layered behind/around this natural height.
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [heading, const SizedBox(height: 30), searchBar],
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
                    height: 80,
                    width: double.infinity,
                    child: const CustomPaint(painter: _HeroWavePainter()),
                  ),
                ),
              ),
            foreground,
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
                        padding: EdgeInsets.all(isNarrow ? 12 : 24),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: const Color(0xFFE5E7EB)),
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
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

    final tabBar = SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (final tab in tabs)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Material(
                color: tab == selectedTab
                    ? const Color(0xFFFCE8EA)
                    : Colors.white,
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
    return Material(
      color: const Color(0xFF5C0A0F),
      borderRadius: BorderRadius.circular(999),
      elevation: 10,
      shadowColor: Colors.black38,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(999),
        child: Padding(
          padding: EdgeInsets.fromLTRB(8, 8, compact ? 14 : 20, 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: compact ? 32 : 36,
                height: compact ? 32 : 36,
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
              Text(
                compact ? 'Chat' : 'Chat with ASKa-Piyu',
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
