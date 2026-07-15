import 'dart:convert';
import 'dart:html' as html;
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_navigation.dart';
import '../design_tokens.dart';
import '../widgets/public_site_header.dart';
import 'chatbot_page.dart';
import 'knowledge_base_page.dart';
import 'my_tickets_page.dart';

/// Public ASKa-Piyu landing page (no sidebar) — matches the branded site mock.
class StudentHomePage extends StatefulWidget {
  const StudentHomePage({super.key});

  @override
  State<StudentHomePage> createState() => _StudentHomePageState();
}

class _StudentHomePageState extends State<StudentHomePage> {
  bool _loading = true;
  String? _error;
  List<_LandingCategory> _categories = const [];
  List<_LandingArticle> _articles = const [];
  String _quickTab = 'Common topics';

  @override
  void initState() {
    super.initState();
    _loadPublicKb();
  }

  Future<void> _loadPublicKb() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final categoriesData = await _getJson('/kb/categories');
      final articlesData = await _getJson('/kb/articles?limit=12');
      final categoryItems =
          categoriesData['items'] is List ? categoriesData['items'] as List : const [];
      final articleItems =
          articlesData['items'] is List ? articlesData['items'] as List : const [];
      if (!mounted) return;
      setState(() {
        _categories = categoryItems
            .whereType<Map>()
            .map((item) =>
                _LandingCategory.fromJson(Map<String, dynamic>.from(item)))
            .where((item) => item.name.isNotEmpty)
            .toList();
        _articles = articleItems
            .whereType<Map>()
            .map((item) =>
                _LandingArticle.fromJson(Map<String, dynamic>.from(item)))
            .toList();
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not load published Knowledge Base content.';
        _loading = false;
      });
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
          CustomScrollView(
            slivers: [
              const SliverToBoxAdapter(child: PublicSiteHeader()),
              SliverToBoxAdapter(child: _HeroSection(isNarrow: isNarrow)),
              // Soft fade from banner into white content
              SliverToBoxAdapter(
                child: Container(
                  height: 36,
                  decoration: const BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [
                        Color(0xFFE8A0A8),
                        Color(0xFFFFF5F6),
                        Colors.white,
                      ],
                    ),
                  ),
                ),
              ),
              SliverToBoxAdapter(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 1120),
                    child: Padding(
                      padding: EdgeInsets.fromLTRB(
                        isNarrow ? 18 : 28,
                        8,
                        isNarrow ? 18 : 28,
                        100,
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'Resources',
                            style: TextStyle(
                              fontSize: 28,
                              fontWeight: FontWeight.w900,
                              color: DesignTokens.ink,
                            ),
                          ),
                          const SizedBox(height: 18),
                          if (_loading)
                            const Padding(
                              padding: EdgeInsets.symmetric(vertical: 40),
                              child: Center(child: CircularProgressIndicator()),
                            )
                          else if (_error != null)
                            Text(
                              _error!,
                              style: const TextStyle(color: DesignTokens.muted),
                            )
                          else if (_categories.isEmpty)
                            const Text(
                              'No published Knowledge Base categories yet.',
                              style: TextStyle(color: DesignTokens.muted),
                            )
                          else
                            _ResourcesGrid(
                              categories: _categories,
                              isNarrow: isNarrow,
                            ),
                          const SizedBox(height: 42),
                          const Text(
                            'Quick links',
                            style: TextStyle(
                              fontSize: 28,
                              fontWeight: FontWeight.w900,
                              color: DesignTokens.ink,
                            ),
                          ),
                          const SizedBox(height: 18),
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
          Positioned(
            right: 20,
            bottom: 20,
            child: _FloatingChatButton(
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ChatbotPage()),
              ),
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
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => KnowledgeBasePage(initialQuery: query),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: Stack(
        children: [
          // Base maroon wash
          Positioned.fill(
            child: Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    Color(0xFF5C0A0F),
                    Color(0xFF7B1113),
                    Color(0xFF9E2A2B),
                    Color(0xFFB85A63),
                  ],
                  stops: [0.0, 0.35, 0.72, 1.0],
                ),
              ),
            ),
          ),
          // Soft lining texture (bottom waves)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            height: 180,
            child: Opacity(
              opacity: 0.55,
              child: Image.asset(
                'assets/hero_waves.png',
                fit: BoxFit.cover,
                alignment: Alignment.bottomCenter,
                filterQuality: FilterQuality.high,
              ),
            ),
          ),
          // Drawn wave lining for crisp layered curves
          Positioned.fill(
            child: CustomPaint(
              painter: _HeroWavePainter(),
            ),
          ),
          Padding(
            padding: EdgeInsets.fromLTRB(
              widget.isNarrow ? 18 : 28,
              widget.isNarrow ? 52 : 76,
              widget.isNarrow ? 18 : 28,
              widget.isNarrow ? 64 : 84,
            ),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 860),
                child: Column(
                  children: [
                    Text(
                      'Welcome to ASKa-Piyu',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                        fontSize: widget.isNarrow ? 34 : 44,
                        height: 1.15,
                      ),
                    ),
                    const SizedBox(height: 14),
                    Text(
                      'Find student support articles, procedures, and answers for Laguna State Polytechnic University.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.92),
                        fontSize: widget.isNarrow ? 15 : 17,
                        height: 1.45,
                      ),
                    ),
                    const SizedBox(height: 28),
                    Container(
                      padding: const EdgeInsets.all(6),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(16),
                        boxShadow: [
                          BoxShadow(
                            color: Colors.black.withValues(alpha: 0.14),
                            blurRadius: 24,
                            offset: const Offset(0, 10),
                          ),
                        ],
                      ),
                      child: Row(
                        children: [
                          const SizedBox(width: 14),
                          Expanded(
                            child: TextField(
                              controller: _searchCtrl,
                              onSubmitted: (_) => _search(),
                              decoration: const InputDecoration(
                                hintText:
                                    'Search articles, policies, offices, or procedures...',
                                border: InputBorder.none,
                                isDense: true,
                                hintStyle: TextStyle(color: Color(0xFF9CA3AF)),
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          SizedBox(
                            height: 44,
                            child: ElevatedButton(
                              onPressed: _search,
                              style: ElevatedButton.styleFrom(
                                backgroundColor: const Color(0xFF5C0A0F),
                                foregroundColor: Colors.white,
                                elevation: 0,
                                padding:
                                    const EdgeInsets.symmetric(horizontal: 22),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(12),
                                ),
                              ),
                              child: const Text(
                                'Search',
                                style: TextStyle(fontWeight: FontWeight.w800),
                              ),
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
        ],
      ),
    );
  }
}

class _HeroWavePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paints = <Paint>[
      Paint()
        ..color = const Color(0x33FFC9CF)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.2,
      Paint()
        ..color = const Color(0x40FFFFFF)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.6,
      Paint()
        ..color = const Color(0x28FFE4E8)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3.0,
    ];

    void drawWave(Paint paint, double baseline, double amplitude, double phase) {
      final path = Path();
      path.moveTo(-20, baseline);
      for (double x = -20; x <= size.width + 20; x += 8) {
        final y = baseline +
            math.sin((x / size.width * 2.4 * math.pi) + phase) * amplitude +
            math.sin((x / size.width * 5.1 * math.pi) + phase * 1.4) *
                (amplitude * 0.35);
        path.lineTo(x, y);
      }
      canvas.drawPath(path, paint);
    }

    final h = size.height;
    drawWave(paints[0], h * 0.68, 18, 0.2);
    drawWave(paints[1], h * 0.76, 14, 1.1);
    drawWave(paints[2], h * 0.84, 22, 2.0);
    drawWave(paints[0], h * 0.90, 12, 2.7);

    // Soft filled ribbon near bottom for depth
    final fill = Path()
      ..moveTo(0, h * 0.88)
      ..cubicTo(size.width * 0.25, h * 0.78, size.width * 0.55, h * 0.98,
          size.width, h * 0.86)
      ..lineTo(size.width, h)
      ..lineTo(0, h)
      ..close();
    canvas.drawPath(
      fill,
      Paint()..color = const Color(0x22FFFFFF),
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _ResourcesGrid extends StatelessWidget {
  final List<_LandingCategory> categories;
  final bool isNarrow;

  const _ResourcesGrid({
    required this.categories,
    required this.isNarrow,
  });

  @override
  Widget build(BuildContext context) {
    final columns = isNarrow
        ? 1
        : MediaQuery.sizeOf(context).width >= 1000
            ? 3
            : 2;
    // Show up to 6 cards like the mock (2 rows x 3).
    final shown = categories.take(6).toList();

    return LayoutBuilder(
      builder: (context, constraints) {
        final gap = 16.0;
        final cardWidth =
            (constraints.maxWidth - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: shown.map((category) {
            return SizedBox(
              width: cardWidth,
              child: Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(14),
                child: InkWell(
                  borderRadius: BorderRadius.circular(14),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => KnowledgeBasePage(
                        initialCategory: category.name,
                      ),
                    ),
                  ),
                  child: Container(
                    constraints: const BoxConstraints(minHeight: 128),
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(color: const Color(0xFFE5E7EB)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          category.name,
                          style: const TextStyle(
                            color: DesignTokens.maroon,
                            fontWeight: FontWeight.w900,
                            fontSize: 17,
                          ),
                        ),
                        const SizedBox(height: 10),
                        Text(
                          category.articleCount > 0
                              ? '${category.articleCount} published article${category.articleCount == 1 ? '' : 's'}'
                              : 'Browse published support articles',
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Color(0xFF4B5563),
                            height: 1.4,
                            fontSize: 14,
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

  List<_QuickLinkItem> _itemsForTab() {
    if (selectedTab == 'Role-based guides') {
      final offices = <String>{};
      for (final article in articles) {
        if (article.office.trim().isNotEmpty) {
          offices.add(article.office.trim());
        }
      }
      if (offices.isEmpty) {
        return categories
            .take(6)
            .map((c) => _QuickLinkItem(
                  title: c.name,
                  subtitle: '${c.articleCount} articles',
                  category: c.name,
                ))
            .toList();
      }
      return offices
          .take(8)
          .map((office) => _QuickLinkItem(
                title: office,
                subtitle: 'Office guide',
                query: office,
              ))
          .toList();
    }
    if (selectedTab == 'Additional resources') {
      // Utility shortcuts only — article browsing lives under Resources / KB.
      return const [
        _QuickLinkItem(
          title: 'Browse Knowledge Base',
          subtitle: 'Search all published support articles',
        ),
        _QuickLinkItem(
          title: 'Ask ASKa-Piyu',
          subtitle: 'Chat with the campus assistant',
          openChat: true,
        ),
        _QuickLinkItem(
          title: 'My Tickets',
          subtitle: 'Track support requests',
          openTickets: true,
        ),
      ];
    }
    // Common topics = published categories with sample article titles.
    return categories
        .take(8)
        .map((c) => _QuickLinkItem(
              title: c.name,
              subtitle: c.description,
              category: c.name,
            ))
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final items = _itemsForTab();
    final sidebar = Container(
      width: isNarrow ? double.infinity : 240,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE5E7EB)),
      ),
      child: Column(
        children: tabs.map((tab) {
          final selected = tab == selectedTab;
          return Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Material(
              color: selected ? const Color(0xFFFCE8EA) : Colors.transparent,
              borderRadius: BorderRadius.circular(10),
              child: InkWell(
                borderRadius: BorderRadius.circular(10),
                onTap: () => onTabChanged(tab),
                child: Container(
                  width: double.infinity,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(10),
                    border: selected
                        ? const Border(
                            left: BorderSide(
                                color: DesignTokens.maroon, width: 3),
                          )
                        : null,
                  ),
                  child: Text(
                    tab,
                    style: TextStyle(
                      fontWeight: FontWeight.w800,
                      color: selected
                          ? DesignTokens.maroon
                          : const Color(0xFF4B5563),
                    ),
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );

    final list = Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE5E7EB)),
      ),
      child: items.isEmpty
          ? const Padding(
              padding: EdgeInsets.all(20),
              child: Text(
                'No published items yet for this section.',
                style: TextStyle(color: DesignTokens.muted),
              ),
            )
          : Column(
              children: [
                for (var i = 0; i < items.length; i++) ...[
                  if (i > 0) const Divider(height: 1, color: Color(0xFFE5E7EB)),
                  _QuickLinkTile(item: items[i]),
                ],
              ],
            ),
    );

    if (isNarrow) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          sidebar,
          const SizedBox(height: 14),
          list,
        ],
      );
    }

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        sidebar,
        const SizedBox(width: 18),
        Expanded(child: list),
      ],
    );
  }
}

class _QuickLinkTile extends StatelessWidget {
  final _QuickLinkItem item;

  const _QuickLinkTile({required this.item});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      child: InkWell(
        onTap: () {
          if (item.openChat) {
            Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const ChatbotPage()),
            );
            return;
          }
          if (item.openTickets) {
            openProtectedPage(
              context,
              builder: (_) => const MyTicketsPage(),
            );
            return;
          }
          Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => KnowledgeBasePage(
                initialCategory: item.category,
                initialQuery: item.query,
              ),
            ),
          );
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.title,
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        color: DesignTokens.ink,
                        fontSize: 15,
                      ),
                    ),
                    if (item.subtitle.trim().isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        item.subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: DesignTokens.muted,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const Icon(Icons.expand_more_rounded, color: DesignTokens.muted),
            ],
          ),
        ),
      ),
    );
  }
}

class _FloatingChatButton extends StatelessWidget {
  final VoidCallback onTap;

  const _FloatingChatButton({required this.onTap});

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
    final count = json['article_count'] is int
        ? json['article_count'] as int
        : int.tryParse('${json['article_count']}') ?? 0;
    final sample =
        json['sample_article_titles'] ?? json['sample_titles'];
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

class _QuickLinkItem {
  final String title;
  final String subtitle;
  final String? category;
  final String? query;
  final bool openChat;
  final bool openTickets;

  const _QuickLinkItem({
    required this.title,
    required this.subtitle,
    this.category,
    this.query,
    this.openChat = false,
    this.openTickets = false,
  });
}

Future<Map<String, dynamic>> _getJson(String path) async {
  final uri = '${AppConfig.resolvedApiBase}$path';
  final request = html.HttpRequest();
  request.open('GET', uri);
  request.send();
  await request.onLoadEnd.first;
  final status = request.status ?? 0;
  final text = (request.responseText ?? '').trim();
  Map<String, dynamic> decoded = {};
  if (text.isNotEmpty) {
    try {
      final value = jsonDecode(text);
      if (value is Map<String, dynamic>) decoded = value;
    } catch (_) {}
  }
  if (status < 200 || status >= 300) {
    throw StateError('Request failed ($status) for $path');
  }
  return decoded;
}
