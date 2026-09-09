import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../services/admin_article_service.dart';
import 'admin_scaffold.dart';
import 'knowledge_article_edit_page.dart';
import 'login_page.dart';
import 'office_scaffold.dart';
import '../widgets/sidebar.dart';

/// Simple article list — tap an article to open the full-page editor.
class KnowledgeArticlesPage extends StatefulWidget {
  const KnowledgeArticlesPage({super.key, this.focusArticleId});

  final String? focusArticleId;

  @override
  State<KnowledgeArticlesPage> createState() => _KnowledgeArticlesPageState();
}

class _KnowledgeArticlesPageState extends State<KnowledgeArticlesPage> {
  late final AdminArticleService _service = AdminArticleService(
    apiBase: AppConfig.resolvedApiBase,
    setAdminHeader: _setAdminHeader,
  );

  final TextEditingController _searchController = TextEditingController();

  List<AdminArticle> _articles = [];
  bool _loading = true;
  String? _error;
  bool _openedFocus = false;

  @override
  void initState() {
    super.initState();
    _searchController.addListener(() => setState(() {}));
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadArticles());
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _setAdminHeader(Map<String, String> headers) {
    final auth = AuthScope.of(context);
    final token = auth.accessToken;
    final role = auth.role;
    if (role != 'admin' && role != 'office') {
      throw StateError('not_admin');
    }
    if (token == null || token.trim().isEmpty) {
      throw StateError('missing_admin_token');
    }
    headers['Authorization'] = 'Bearer $token';
  }

  Future<void> _loadArticles() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final articles = await _service.listArticles();
      if (!mounted) return;
      setState(() => _articles = _sortArticles(articles));
      await _maybeOpenFocus();
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<AdminArticle> _sortArticles(List<AdminArticle> articles) {
    final sorted = List<AdminArticle>.from(articles);
    sorted.sort((a, b) {
      if (a.published != b.published) {
        return a.published ? -1 : 1;
      }
      final aUpdated = a.updatedAt ?? a.publishedAt ?? '';
      final bUpdated = b.updatedAt ?? b.publishedAt ?? '';
      if (aUpdated.isNotEmpty && bUpdated.isNotEmpty) {
        return bUpdated.compareTo(aUpdated);
      }
      return a.title.toLowerCase().compareTo(b.title.toLowerCase());
    });
    return sorted;
  }

  List<AdminArticle> get _visibleArticles {
    final query = _searchController.text.trim().toLowerCase();
    if (query.isEmpty) return _articles;
    return _articles.where((article) {
      final haystack = [
        article.title,
        article.category,
        article.office ?? '',
        article.sourceFilename ?? '',
      ].join(' ').toLowerCase();
      return haystack.contains(query);
    }).toList();
  }

  int get _publishedCount => _articles.where((a) => a.published).length;
  int get _draftCount => _articles.where((a) => !a.published).length;

  Future<void> _maybeOpenFocus() async {
    if (_openedFocus) return;
    final focusId = (widget.focusArticleId ?? '').trim();
    if (focusId.isEmpty) return;
    AdminArticle? article;
    for (final candidate in _articles) {
      if (candidate.id == focusId) {
        article = candidate;
        break;
      }
    }
    if (article == null) return;
    _openedFocus = true;
    await _openEdit(article);
  }

  Future<void> _openEdit(AdminArticle article) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => KnowledgeArticleEditPage(
          articleId: article.id,
          setAdminHeader: _setAdminHeader,
        ),
      ),
    );
    if (saved == true && mounted) {
      await _loadArticles();
    }
  }

  Widget _buildContent() {
    if (_loading && _articles.isEmpty) {
      return const Center(
        child: CircularProgressIndicator(color: DesignTokens.maroon),
      );
    }

    if (_error != null) {
      return Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.error_outline_rounded,
                  size: 40, color: Colors.red.shade400),
              const SizedBox(height: 12),
              SelectableText(
                _error!,
                style: TextStyle(color: Colors.red.shade700, height: 1.5),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: _loadArticles,
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: const Text('Try again'),
              ),
            ],
          ),
        ),
      );
    }

    if (_articles.isEmpty) {
      return Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: DesignTokens.maroon.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: const Icon(
                  Icons.article_outlined,
                  color: DesignTokens.maroon,
                  size: 28,
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                'No articles yet',
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  color: DesignTokens.ink,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Publish from a resolved ticket or generate articles in Knowledge Base.',
                style: TextStyle(color: DesignTokens.muted, height: 1.5),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    final visible = _visibleArticles;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ArticleStatsRow(
          total: _articles.length,
          published: _publishedCount,
          drafts: _draftCount,
        ),
        const SizedBox(height: 14),
        TextField(
          controller: _searchController,
          decoration: InputDecoration(
            hintText: 'Search by title, category, or source…',
            prefixIcon: const Icon(Icons.search_rounded, size: 22),
            suffixIcon: _searchController.text.trim().isEmpty
                ? null
                : IconButton(
                    tooltip: 'Clear search',
                    onPressed: () => _searchController.clear(),
                    icon: const Icon(Icons.close_rounded, size: 20),
                  ),
            filled: true,
            fillColor: Colors.white,
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: DesignTokens.border),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: DesignTokens.border),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.5),
            ),
            isDense: true,
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          ),
        ),
        const SizedBox(height: 14),
        Row(
          children: [
            Text(
              visible.length == _articles.length
                  ? '${_articles.length} article${_articles.length == 1 ? '' : 's'}'
                  : '${visible.length} of ${_articles.length} articles',
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w800,
                color: DesignTokens.ink,
              ),
            ),
            const Spacer(),
            if (_loading)
              const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: DesignTokens.maroon,
                ),
              )
            else
              IconButton(
                tooltip: 'Refresh',
                onPressed: _loadArticles,
                icon: const Icon(Icons.refresh_rounded, size: 22),
                color: DesignTokens.muted,
              ),
          ],
        ),
        const SizedBox(height: 8),
        Expanded(
          child: visible.isEmpty
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.search_off_rounded,
                          size: 36, color: DesignTokens.muted.withValues(alpha: 0.7)),
                      const SizedBox(height: 10),
                      const Text(
                        'No articles match your search',
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          color: DesignTokens.muted,
                        ),
                      ),
                    ],
                  ),
                )
              : ListView.separated(
                  padding: const EdgeInsets.only(bottom: 8),
                  itemCount: visible.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (context, index) {
                    return _KnowledgeArticleRow(
                      article: visible[index],
                      onTap: () => _openEdit(visible[index]),
                    );
                  },
                ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    if (auth.isLoading) {
      return const Scaffold(
        backgroundColor: DesignTokens.adminSurface,
        body: Center(
          child: CircularProgressIndicator(color: DesignTokens.maroon),
        ),
      );
    }
    if (!auth.isAuthenticated) {
      return Scaffold(
        backgroundColor: DesignTokens.adminSurface,
        body: Center(
          child: ElevatedButton(
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => LoginPage(
                  returnTo: (_) => KnowledgeArticlesPage(
                    focusArticleId: widget.focusArticleId,
                  ),
                ),
              ),
            ),
            child: const Text('Login'),
          ),
        ),
      );
    }
    if (auth.role != 'admin' && auth.role != 'office') {
      return const Scaffold(
        backgroundColor: DesignTokens.adminSurface,
        body: Center(child: Text('Admin or office access required.')),
      );
    }

    final isOffice = auth.role == 'office';
    final content = Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
      child: _buildContent(),
    );

    if (isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeKnowledgeArticles,
        title: 'Knowledge Article',
        description:
            'Browse and update your office articles for the public Knowledge Base.',
        fillBody: true,
        child: content,
      );
    }

    return AdminScaffold(
      current: StudentNavItem.adminKnowledgeArticles,
      title: 'Knowledge Article',
      description: 'Browse, edit, and publish Knowledge Base articles.',
      fillBody: true,
      child: content,
    );
  }
}

class _ArticleStatsRow extends StatelessWidget {
  const _ArticleStatsRow({
    required this.total,
    required this.published,
    required this.drafts,
  });

  final int total;
  final int published;
  final int drafts;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 520;
        final children = [
          _ArticleStatTile(
            label: 'Total',
            value: total,
            icon: Icons.library_books_outlined,
            accent: DesignTokens.ink,
          ),
          _ArticleStatTile(
            label: 'Published',
            value: published,
            icon: Icons.public_rounded,
            accent: const Color(0xFF15803D),
          ),
          _ArticleStatTile(
            label: 'Drafts',
            value: drafts,
            icon: Icons.edit_note_rounded,
            accent: const Color(0xFFB45309),
          ),
        ];
        if (compact) {
          return Column(
            children: [
              for (var i = 0; i < children.length; i++) ...[
                if (i > 0) const SizedBox(height: 8),
                children[i],
              ],
            ],
          );
        }
        return Row(
          children: [
            for (var i = 0; i < children.length; i++) ...[
              if (i > 0) const SizedBox(width: 10),
              Expanded(child: children[i]),
            ],
          ],
        );
      },
    );
  }
}

class _ArticleStatTile extends StatelessWidget {
  const _ArticleStatTile({
    required this.label,
    required this.value,
    required this.icon,
    required this.accent,
  });

  final String label;
  final int value;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, size: 18, color: accent),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '$value',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w900,
                    color: accent,
                    height: 1.1,
                  ),
                ),
                Text(
                  label,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: DesignTokens.muted,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _KnowledgeArticleRow extends StatelessWidget {
  const _KnowledgeArticleRow({
    required this.article,
    required this.onTap,
  });

  final AdminArticle article;
  final VoidCallback onTap;

  String _formatUpdated() {
    final raw = (article.updatedAt ?? article.publishedAt ?? '').trim();
    if (raw.isEmpty) return '';
    try {
      final dt = DateTime.parse(raw).toLocal();
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ];
      return 'Updated ${months[dt.month - 1]} ${dt.day}, ${dt.year}';
    } catch (_) {
      return '';
    }
  }

  @override
  Widget build(BuildContext context) {
    final updated = _formatUpdated();
    final metaParts = <String>[
      if (article.category.trim().isNotEmpty) article.category.trim(),
      if (updated.isNotEmpty) updated,
    ];

    return Material(
      color: Colors.white,
      elevation: 0,
      shadowColor: Colors.transparent,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Ink(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: DesignTokens.border),
            boxShadow: DesignTokens.softShadow(0.03),
          ),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          _ArticleStatusChip(published: article.published),
                          if (article.published && article.ragIndexed)
                            const _ArticleMetaChip(
                              label: 'In chatbot',
                              background: Color(0xFFDCFCE7),
                              foreground: Color(0xFF166534),
                            ),
                          if (article.ragStale)
                            const _ArticleMetaChip(
                              label: 'Needs reindex',
                              background: Color(0xFFFEE2E2),
                              foreground: Color(0xFFB91C1C),
                            ),
                          if (!article.published && article.needsReview)
                            const _ArticleMetaChip(
                              label: 'Needs review',
                              background: Color(0xFFFFF7ED),
                              foreground: Color(0xFFC2410C),
                            ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Text(
                        article.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w800,
                          color: DesignTokens.ink,
                          height: 1.35,
                        ),
                      ),
                      if (metaParts.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          metaParts.join(' · '),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: DesignTokens.muted,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                const Padding(
                  padding: EdgeInsets.only(top: 2),
                  child: Icon(
                    Icons.chevron_right_rounded,
                    color: DesignTokens.muted,
                    size: 24,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ArticleStatusChip extends StatelessWidget {
  const _ArticleStatusChip({required this.published});

  final bool published;

  @override
  Widget build(BuildContext context) {
    if (published) {
      return const _ArticleMetaChip(
        label: 'Published',
        background: Color(0xFFFCE7F3),
        foreground: DesignTokens.maroon,
      );
    }
    return const _ArticleMetaChip(
      label: 'Draft',
      background: Color(0xFFF1F5F9),
      foreground: Color(0xFF475569),
    );
  }
}

class _ArticleMetaChip extends StatelessWidget {
  const _ArticleMetaChip({
    required this.label,
    required this.background,
    required this.foreground,
  });

  final String label;
  final Color background;
  final Color foreground;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w800,
          color: foreground,
          letterSpacing: 0.1,
        ),
      ),
    );
  }
}
