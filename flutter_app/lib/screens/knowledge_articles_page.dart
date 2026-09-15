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

const int _kArticlePageSize = 10;

/// Shared Admin/Office article list. Office data is already scoped by the API.
class KnowledgeArticlesPage extends StatefulWidget {
  const KnowledgeArticlesPage({
    super.key,
    this.focusArticleId,
    this.debugArticles,
    this.debugLoading = false,
    this.debugError,
  });

  final String? focusArticleId;

  /// Seeded articles skip network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugArticles;

  @visibleForTesting
  final bool debugLoading;

  @visibleForTesting
  final String? debugError;

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
  String _officeFilter = 'All';
  String _categoryFilter = 'All';
  String _statusFilter = 'All';
  int _page = 1;

  @override
  void initState() {
    super.initState();
    if (!_applyDebugSeed()) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _loadArticles());
    }
  }

  @override
  void didUpdateWidget(KnowledgeArticlesPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.debugArticles != oldWidget.debugArticles ||
        widget.debugLoading != oldWidget.debugLoading ||
        widget.debugError != oldWidget.debugError) {
      _applyDebugSeed();
    }
  }

  bool _applyDebugSeed() {
    final seeded = widget.debugArticles;
    if (seeded != null) {
      _loading = widget.debugLoading;
      _error = widget.debugError;
      _articles = _sortArticles(
        seeded.map(AdminArticle.fromListJson).toList(),
      );
      return true;
    }
    if (widget.debugLoading || widget.debugError != null) {
      _loading = widget.debugLoading;
      _error = widget.debugError;
      return true;
    }
    return false;
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

  bool get _isAdmin => AuthScope.of(context).role == 'admin';
  bool get _canDelete => _isAdmin;
  bool get _canCreate =>
      AuthScope.of(context).role == 'admin' ||
      AuthScope.of(context).role == 'office';

  Future<void> _loadArticles() async {
    if (widget.debugArticles != null ||
        widget.debugLoading ||
        widget.debugError != null) {
      setState(() {
        _loading = widget.debugLoading;
        _error = widget.debugError;
        if (widget.debugArticles != null) {
          _articles = _sortArticles(
            widget.debugArticles!.map(AdminArticle.fromListJson).toList(),
          );
        }
      });
      return;
    }

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
      final aUpdated = a.updatedAt ?? a.publishedAt ?? '';
      final bUpdated = b.updatedAt ?? b.publishedAt ?? '';
      if (aUpdated.isNotEmpty && bUpdated.isNotEmpty) {
        return bUpdated.compareTo(aUpdated);
      }
      return a.title.toLowerCase().compareTo(b.title.toLowerCase());
    });
    return sorted;
  }

  List<String> get _officeOptions {
    final values = _articles
        .map((article) => displayOffice(article.office))
        .where((value) => value.isNotEmpty && value != 'Not specified')
        .toSet()
        .toList()
      ..sort();
    return ['All', ...values];
  }

  List<String> get _categoryOptions {
    final values = _articles
        .map((article) => article.category.trim())
        .where((value) => value.isNotEmpty)
        .toSet()
        .toList()
      ..sort();
    return ['All', ...values];
  }

  List<AdminArticle> get _filteredArticles {
    final query = _searchController.text.trim().toLowerCase();
    return _articles.where((article) {
      if (_officeFilter != 'All' &&
          displayOffice(article.office) != _officeFilter) {
        return false;
      }
      if (_categoryFilter != 'All' &&
          article.category.trim() != _categoryFilter) {
        return false;
      }
      if (_statusFilter == 'Published' && !article.published) return false;
      if (_statusFilter == 'Draft' && article.published) return false;
      if (query.isEmpty) return true;
      final haystack = [
        article.title,
        article.summary ?? '',
        article.category,
        article.office ?? '',
        article.sourceFilename ?? '',
      ].join(' ').toLowerCase();
      return haystack.contains(query);
    }).toList();
  }

  int get _publishedCount => _articles.where((a) => a.published).length;
  int get _draftCount => _articles.where((a) => !a.published).length;
  int get _categoryCount => _articles
      .map((article) => article.category.trim())
      .where((value) => value.isNotEmpty)
      .toSet()
      .length;

  int get _pageCount {
    final total = _filteredArticles.length;
    if (total == 0) return 1;
    return ((total - 1) / _kArticlePageSize).floor() + 1;
  }

  int get _safePage {
    final last = _pageCount;
    if (_page > last) return last;
    if (_page < 1) return 1;
    return _page;
  }

  List<AdminArticle> get _pageArticles {
    final filtered = _filteredArticles;
    final start = (_safePage - 1) * _kArticlePageSize;
    if (start >= filtered.length) return const [];
    final end = (start + _kArticlePageSize).clamp(0, filtered.length);
    return filtered.sublist(start, end);
  }

  void _resetFilters() {
    setState(() {
      _searchController.clear();
      _officeFilter = 'All';
      _categoryFilter = 'All';
      _statusFilter = 'All';
      _page = 1;
    });
  }

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

  Future<void> _openCreate() async {
    final created = await showDialog<AdminArticle>(
      context: context,
      builder: (_) => _KnowledgeCreateArticleDialog(
        service: _service,
        lockOfficeTo: _isAdmin
            ? null
            : AuthScope.of(context).currentUser?.officeName,
      ),
    );
    if (created == null || !mounted) return;
    await _loadArticles();
    if (!mounted) return;
    await _openEdit(created);
  }

  Future<void> _confirmDelete(AdminArticle article) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete article?'),
        content: Text(
          'Delete "${article.title}"? This removes the article and cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: TextButton.styleFrom(foregroundColor: const Color(0xFFB91C1C)),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await _service.deleteArticle(article.id);
      if (!mounted) return;
      await _loadArticles();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Deleted "${article.title}".')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString())),
      );
    }
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
    final content = _KnowledgeArticleWorkspace(
      loading: _loading,
      error: _error,
      articles: _articles,
      filtered: _filteredArticles,
      pageArticles: _pageArticles,
      page: _safePage,
      pageCount: _pageCount,
      pageSize: _kArticlePageSize,
      total: _articles.length,
      published: _publishedCount,
      drafts: _draftCount,
      categories: _categoryCount,
      searchCtrl: _searchController,
      showOfficeFilter: _isAdmin,
      officeOptions: _officeOptions,
      categoryOptions: _categoryOptions,
      officeFilter: _officeFilter,
      categoryFilter: _categoryFilter,
      statusFilter: _statusFilter,
      canDelete: _canDelete,
      canCreate: _canCreate,
      onRetry: _loadArticles,
      onSearch: () => setState(() => _page = 1),
      onReset: _resetFilters,
      onOfficeChanged: (value) => setState(() {
        _officeFilter = value;
        _page = 1;
      }),
      onCategoryChanged: (value) => setState(() {
        _categoryFilter = value;
        _page = 1;
      }),
      onStatusChanged: (value) => setState(() {
        _statusFilter = value;
        _page = 1;
      }),
      onPageChanged: (page) => setState(() => _page = page),
      onCreate: _canCreate ? _openCreate : null,
      onEdit: _openEdit,
      onDelete: _canDelete ? _confirmDelete : null,
    );

    if (isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeKnowledgeArticles,
        title: 'Knowledge Article',
        description:
            'Browse, edit, and publish Knowledge Base articles.',
        fillBody: true,
        showHeader: false,
        child: content,
      );
    }

    return AdminScaffold(
      current: StudentNavItem.adminKnowledgeArticles,
      title: 'Knowledge Article',
      description: 'Browse, edit, and publish Knowledge Base articles.',
      fillBody: true,
      showHeader: false,
      child: content,
    );
  }

}

class _KnowledgeArticleWorkspace extends StatelessWidget {
  const _KnowledgeArticleWorkspace({
    required this.loading,
    required this.error,
    required this.articles,
    required this.filtered,
    required this.pageArticles,
    required this.page,
    required this.pageCount,
    required this.pageSize,
    required this.total,
    required this.published,
    required this.drafts,
    required this.categories,
    required this.searchCtrl,
    required this.showOfficeFilter,
    required this.officeOptions,
    required this.categoryOptions,
    required this.officeFilter,
    required this.categoryFilter,
    required this.statusFilter,
    required this.canDelete,
    required this.canCreate,
    required this.onRetry,
    required this.onSearch,
    required this.onReset,
    required this.onOfficeChanged,
    required this.onCategoryChanged,
    required this.onStatusChanged,
    required this.onPageChanged,
    required this.onCreate,
    required this.onEdit,
    required this.onDelete,
  });

  final bool loading;
  final String? error;
  final List<AdminArticle> articles;
  final List<AdminArticle> filtered;
  final List<AdminArticle> pageArticles;
  final int page;
  final int pageCount;
  final int pageSize;
  final int total;
  final int published;
  final int drafts;
  final int categories;
  final TextEditingController searchCtrl;
  final bool showOfficeFilter;
  final List<String> officeOptions;
  final List<String> categoryOptions;
  final String officeFilter;
  final String categoryFilter;
  final String statusFilter;
  final bool canDelete;
  final bool canCreate;
  final VoidCallback onRetry;
  final VoidCallback onSearch;
  final VoidCallback onReset;
  final ValueChanged<String> onOfficeChanged;
  final ValueChanged<String> onCategoryChanged;
  final ValueChanged<String> onStatusChanged;
  final ValueChanged<int> onPageChanged;
  final VoidCallback? onCreate;
  final ValueChanged<AdminArticle> onEdit;
  final ValueChanged<AdminArticle>? onDelete;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (loading) const LinearProgressIndicator(minHeight: 3),
        Expanded(
          child: LayoutBuilder(
            builder: (context, constraints) {
              final wide = constraints.maxWidth >= 900;
              final compact = constraints.maxWidth < 720;
              return SingleChildScrollView(
                padding: EdgeInsets.fromLTRB(
                  wide ? 24 : 14,
                  wide ? 20 : 14,
                  wide ? 24 : 14,
                  24,
                ),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 1180),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _KnowledgeArticleHeader(onCreate: onCreate),
                      const SizedBox(height: 18),
                      _KnowledgeArticleStatsRow(
                        total: total,
                        published: published,
                        drafts: drafts,
                        categories: categories,
                      ),
                      const SizedBox(height: 16),
                      _KnowledgeArticleFilters(
                        searchCtrl: searchCtrl,
                        showOfficeFilter: showOfficeFilter,
                        officeOptions: officeOptions,
                        categoryOptions: categoryOptions,
                        officeFilter: officeFilter,
                        categoryFilter: categoryFilter,
                        statusFilter: statusFilter,
                        onSearch: onSearch,
                        onReset: onReset,
                        onOfficeChanged: onOfficeChanged,
                        onCategoryChanged: onCategoryChanged,
                        onStatusChanged: onStatusChanged,
                      ),
                      const SizedBox(height: 16),
                      _KnowledgeArticlePanel(
                        loading: loading,
                        error: error,
                        hasAny: articles.isNotEmpty,
                        filteredCount: filtered.length,
                        pageArticles: pageArticles,
                        compact: compact,
                        canDelete: canDelete,
                        onRetry: onRetry,
                        onEdit: onEdit,
                        onDelete: onDelete,
                        pager: filtered.isEmpty
                            ? null
                            : _KnowledgeArticlePager(
                                page: page,
                                pageCount: pageCount,
                                pageSize: pageSize,
                                filteredCount: filtered.length,
                                onPageChanged: onPageChanged,
                              ),
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }
}

class _KnowledgeArticleHeader extends StatelessWidget {
  const _KnowledgeArticleHeader({required this.onCreate});

  final VoidCallback? onCreate;

  @override
  Widget build(BuildContext context) {
    final title = const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'KNOWLEDGE BASE',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
            letterSpacing: 1.1,
          ),
        ),
        SizedBox(height: 6),
        Text(
          'Knowledge Article',
          style: TextStyle(
            color: DesignTokens.ink,
            fontSize: 28,
            fontWeight: FontWeight.w900,
            height: 1.1,
          ),
        ),
        SizedBox(height: 6),
        Text(
          'Browse, edit, and publish Knowledge Base articles.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 13,
            fontWeight: FontWeight.w600,
            height: 1.35,
          ),
        ),
      ],
    );
    final create = onCreate == null
        ? null
        : ElevatedButton(
            key: const Key('knowledge-article-create'),
            onPressed: onCreate,
            style: ElevatedButton.styleFrom(
              backgroundColor: DesignTokens.maroon,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
            ),
            child: const Text(
              'Create Article',
              style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
            ),
          );

    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 560 || create == null) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              title,
              if (create != null) ...[
                const SizedBox(height: 12),
                create,
              ],
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: title),
            const SizedBox(width: 12),
            create,
          ],
        );
      },
    );
  }
}

class _KnowledgeArticleStatsRow extends StatelessWidget {
  const _KnowledgeArticleStatsRow({
    required this.total,
    required this.published,
    required this.drafts,
    required this.categories,
  });

  final int total;
  final int published;
  final int drafts;
  final int categories;

  @override
  Widget build(BuildContext context) {
    final stats = [
      _KnowledgeStatData('Total Articles', '$total', DesignTokens.ink),
      _KnowledgeStatData('Published', '$published', const Color(0xFF15803D)),
      _KnowledgeStatData('Drafts', '$drafts', const Color(0xFFB45309)),
      _KnowledgeStatData('Categories', '$categories', DesignTokens.ink),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final columns = width >= 900
            ? 4
            : width >= 560
                ? 2
                : 1;
        const gap = 12.0;
        final cardWidth = columns == 1
            ? width
            : (width - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: stats
              .map(
                (stat) => SizedBox(
                  width: cardWidth,
                  child: _KnowledgeStatCard(data: stat),
                ),
              )
              .toList(),
        );
      },
    );
  }
}

class _KnowledgeStatData {
  const _KnowledgeStatData(this.label, this.value, this.accent);

  final String label;
  final String value;
  final Color accent;
}

class _KnowledgeStatCard extends StatelessWidget {
  const _KnowledgeStatCard({required this.data});

  final _KnowledgeStatData data;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            data.label,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            data.value,
            style: TextStyle(
              color: data.accent,
              fontSize: 28,
              fontWeight: FontWeight.w800,
              height: 1,
            ),
          ),
        ],
      ),
    );
  }
}

class _KnowledgeArticleFilters extends StatelessWidget {
  const _KnowledgeArticleFilters({
    required this.searchCtrl,
    required this.showOfficeFilter,
    required this.officeOptions,
    required this.categoryOptions,
    required this.officeFilter,
    required this.categoryFilter,
    required this.statusFilter,
    required this.onSearch,
    required this.onReset,
    required this.onOfficeChanged,
    required this.onCategoryChanged,
    required this.onStatusChanged,
  });

  final TextEditingController searchCtrl;
  final bool showOfficeFilter;
  final List<String> officeOptions;
  final List<String> categoryOptions;
  final String officeFilter;
  final String categoryFilter;
  final String statusFilter;
  final VoidCallback onSearch;
  final VoidCallback onReset;
  final ValueChanged<String> onOfficeChanged;
  final ValueChanged<String> onCategoryChanged;
  final ValueChanged<String> onStatusChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final wrap = constraints.maxWidth < 900;
          final search = TextField(
            key: const Key('knowledge-article-search'),
            controller: searchCtrl,
            onSubmitted: (_) => onSearch(),
            decoration: InputDecoration(
              hintText: 'Search by title, content, or keyword...',
              prefixIcon: const Icon(Icons.search_rounded, size: 18),
              isDense: true,
              filled: true,
              fillColor: const Color(0xFFF8FAFC),
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: const BorderSide(color: DesignTokens.border),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: const BorderSide(color: DesignTokens.border),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide:
                    const BorderSide(color: DesignTokens.maroon, width: 1.2),
              ),
            ),
          );
          final filters = [
            if (showOfficeFilter)
              _filterDropdown(
                key: const Key('knowledge-article-office-filter'),
                value: officeFilter,
                items: officeOptions
                    .map((value) => value == 'All' ? 'All Offices' : value)
                    .toList(),
                rawValues: officeOptions,
                onChanged: onOfficeChanged,
              ),
            _filterDropdown(
              key: const Key('knowledge-article-category-filter'),
              value: categoryFilter,
              items: categoryOptions
                  .map((value) => value == 'All' ? 'All Categories' : value)
                  .toList(),
              rawValues: categoryOptions,
              onChanged: onCategoryChanged,
            ),
            _filterDropdown(
              key: const Key('knowledge-article-status-filter'),
              value: statusFilter,
              items: const ['All Status', 'Published', 'Draft'],
              rawValues: const ['All', 'Published', 'Draft'],
              onChanged: onStatusChanged,
            ),
          ];
          final actions = Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              ElevatedButton(
                key: const Key('knowledge-article-search-btn'),
                onPressed: onSearch,
                style: ElevatedButton.styleFrom(
                  backgroundColor: DesignTokens.maroon,
                  foregroundColor: Colors.white,
                  minimumSize: const Size(88, 40),
                ),
                child: const Text('Search'),
              ),
              const SizedBox(width: 8),
              OutlinedButton(
                key: const Key('knowledge-article-reset'),
                onPressed: onReset,
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(88, 40),
                  foregroundColor: DesignTokens.ink,
                ),
                child: const Text('Reset'),
              ),
            ],
          );

          if (wrap) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                search,
                const SizedBox(height: 10),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  ...filters.map((child) => SizedBox(width: 200, child: child)),
                  actions,
                ]),
              ],
            );
          }

          return Row(
            children: [
              Expanded(flex: 3, child: search),
              const SizedBox(width: 10),
              for (final filter in filters) ...[
                Expanded(child: filter),
                const SizedBox(width: 8),
              ],
              actions,
            ],
          );
        },
      ),
    );
  }

  Widget _filterDropdown({
    required Key key,
    required String value,
    required List<String> items,
    required List<String> rawValues,
    required ValueChanged<String> onChanged,
  }) {
    return DropdownButtonFormField<String>(
      key: key,
      value: value,
      isExpanded: true,
      decoration: InputDecoration(
        isDense: true,
        filled: true,
        fillColor: const Color(0xFFF8FAFC),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: DesignTokens.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: DesignTokens.border),
        ),
      ),
      items: [
        for (var i = 0; i < rawValues.length; i++)
          DropdownMenuItem(
            value: rawValues[i],
            child: Text(items[i], overflow: TextOverflow.ellipsis),
          ),
      ],
      onChanged: (next) {
        if (next != null) onChanged(next);
      },
    );
  }
}

class _KnowledgeArticlePanel extends StatelessWidget {
  const _KnowledgeArticlePanel({
    required this.loading,
    required this.error,
    required this.hasAny,
    required this.filteredCount,
    required this.pageArticles,
    required this.compact,
    required this.canDelete,
    required this.onRetry,
    required this.onEdit,
    required this.onDelete,
    this.pager,
  });

  final bool loading;
  final String? error;
  final bool hasAny;
  final int filteredCount;
  final List<AdminArticle> pageArticles;
  final bool compact;
  final bool canDelete;
  final VoidCallback onRetry;
  final ValueChanged<AdminArticle> onEdit;
  final ValueChanged<AdminArticle>? onDelete;
  final Widget? pager;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      padding: const EdgeInsets.fromLTRB(8, 8, 8, 8),
      child: Builder(
        builder: (context) {
          if (loading && !hasAny) {
            return const _KnowledgeArticleState(
              title: 'Loading articles',
              body: 'Fetching Knowledge Base articles.',
            );
          }
          if (error != null && !hasAny) {
            return _KnowledgeArticleState(
              title: 'Could not load articles',
              body: error!,
              actionLabel: 'Try again',
              onAction: onRetry,
            );
          }
          if (!hasAny) {
            return const _KnowledgeArticleState(
              title: 'No articles yet',
              body:
                  'Publish from a resolved ticket or generate articles in Knowledge Base.',
            );
          }
          if (filteredCount == 0) {
            return const _KnowledgeArticleState(
              title: 'No articles match this search',
              body: 'Try a different title, category, or status, or reset filters.',
            );
          }
          Widget body;
          if (compact) {
            body = Column(
              children: [
                for (var i = 0; i < pageArticles.length; i++) ...[
                  _KnowledgeArticleCard(
                    article: pageArticles[i],
                    canDelete: canDelete,
                    onEdit: () => onEdit(pageArticles[i]),
                    onDelete: onDelete == null
                        ? null
                        : () => onDelete!(pageArticles[i]),
                  ),
                  if (i != pageArticles.length - 1) const SizedBox(height: 8),
                ],
              ],
            );
          } else {
            body = _KnowledgeArticleTable(
              articles: pageArticles,
              canDelete: canDelete,
              onEdit: onEdit,
              onDelete: onDelete,
            );
          }
          if (pager == null) return body;
          return Column(
            children: [
              body,
              const Divider(height: 1, color: DesignTokens.border),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
                child: pager!,
              ),
            ],
          );
        },
      ),
    );
  }
}

class _KnowledgeArticleState extends StatelessWidget {
  const _KnowledgeArticleState({
    required this.title,
    required this.body,
    this.actionLabel,
    this.onAction,
  });

  final String title;
  final String body;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 16),
      child: Column(
        children: [
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            body,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 13,
              fontWeight: FontWeight.w600,
              height: 1.4,
            ),
          ),
          if (actionLabel != null && onAction != null) ...[
            const SizedBox(height: 14),
            OutlinedButton(onPressed: onAction, child: Text(actionLabel!)),
          ],
        ],
      ),
    );
  }
}

class _KnowledgeArticleTable extends StatelessWidget {
  const _KnowledgeArticleTable({
    required this.articles,
    required this.canDelete,
    required this.onEdit,
    required this.onDelete,
  });

  final List<AdminArticle> articles;
  final bool canDelete;
  final ValueChanged<AdminArticle> onEdit;
  final ValueChanged<AdminArticle>? onDelete;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(12, 8, 12, 8),
          child: Row(
            children: [
              Expanded(flex: 4, child: Text('TITLE', style: _kHeader)),
              Expanded(flex: 3, child: Text('OFFICE', style: _kHeader)),
              Expanded(flex: 2, child: Text('CATEGORY', style: _kHeader)),
              Expanded(flex: 2, child: Text('STATUS', style: _kHeader)),
              Expanded(flex: 2, child: Text('UPDATED AT', style: _kHeader)),
              SizedBox(
                width: 120,
                child: Text('ACTIONS', style: _kHeader, textAlign: TextAlign.right),
              ),
            ],
          ),
        ),
        const Divider(height: 1, color: DesignTokens.border),
        for (var i = 0; i < articles.length; i++) ...[
          _KnowledgeArticleTableRow(
            article: articles[i],
            canDelete: canDelete,
            onEdit: () => onEdit(articles[i]),
            onDelete: onDelete == null ? null : () => onDelete!(articles[i]),
          ),
          if (i != articles.length - 1)
            const Divider(height: 1, color: DesignTokens.border),
        ],
      ],
    );
  }
}

const TextStyle _kHeader = TextStyle(
  color: DesignTokens.muted,
  fontSize: 11,
  fontWeight: FontWeight.w800,
  letterSpacing: 0.4,
);

class _KnowledgeArticleTableRow extends StatelessWidget {
  const _KnowledgeArticleTableRow({
    required this.article,
    required this.canDelete,
    required this.onEdit,
    required this.onDelete,
  });

  final AdminArticle article;
  final bool canDelete;
  final VoidCallback onEdit;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onEdit,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        child: Row(
          children: [
            Expanded(
              flex: 4,
              child: Text(
                article.title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w700,
                  fontSize: 13,
                ),
              ),
            ),
            Expanded(
              flex: 3,
              child: Text(
                displayOffice(article.office),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
            ),
            Expanded(
              flex: 2,
              child: Text(
                article.category,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
            ),
            Expanded(
              flex: 2,
              child: Align(
                alignment: Alignment.centerLeft,
                child: _KnowledgeStatusBadge(published: article.published),
              ),
            ),
            Expanded(
              flex: 2,
              child: Text(
                _formatArticleDate(article.updatedAt ?? article.publishedAt),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
            ),
            SizedBox(
              width: 120,
              child: Align(
                alignment: Alignment.centerRight,
                child: _KnowledgeArticleActions(
                  article: article,
                  canDelete: canDelete,
                  onEdit: onEdit,
                  onDelete: onDelete,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _KnowledgeArticleCard extends StatelessWidget {
  const _KnowledgeArticleCard({
    required this.article,
    required this.canDelete,
    required this.onEdit,
    required this.onDelete,
  });

  final AdminArticle article;
  final bool canDelete;
  final VoidCallback onEdit;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xFFF8FAFC),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onEdit,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: DesignTokens.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                article.title,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w800,
                  fontSize: 14,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                '${displayOffice(article.office)} · ${article.category}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  _KnowledgeStatusBadge(published: article.published),
                  Text(
                    _formatArticleDate(
                      article.updatedAt ?? article.publishedAt,
                    ),
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  _KnowledgeArticleActions(
                    article: article,
                    canDelete: canDelete,
                    onEdit: onEdit,
                    onDelete: onDelete,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _KnowledgeArticleActions extends StatelessWidget {
  const _KnowledgeArticleActions({
    required this.article,
    required this.canDelete,
    required this.onEdit,
    required this.onDelete,
  });

  final AdminArticle article;
  final bool canDelete;
  final VoidCallback onEdit;
  final VoidCallback? onDelete;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 2,
      runSpacing: 0,
      alignment: WrapAlignment.end,
      children: [
        _actionLink(
          key: Key('knowledge-article-edit-${article.id}'),
          label: 'Edit',
          color: DesignTokens.ink,
          onTap: onEdit,
        ),
        if (canDelete && onDelete != null)
          _actionLink(
            key: Key('knowledge-article-delete-${article.id}'),
            label: 'Delete',
            color: const Color(0xFFB91C1C),
            onTap: onDelete!,
          ),
      ],
    );
  }

  Widget _actionLink({
    required Key key,
    required String label,
    required Color color,
    required VoidCallback onTap,
  }) {
    return InkWell(
      key: key,
      onTap: onTap,
      borderRadius: BorderRadius.circular(6),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
        child: Text(
          label,
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.w800,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}

class _KnowledgeStatusBadge extends StatelessWidget {
  const _KnowledgeStatusBadge({required this.published});

  final bool published;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: published ? const Color(0xFFDCFCE7) : const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        published ? 'Published' : 'Draft',
        style: TextStyle(
          color: published ? const Color(0xFF15803D) : const Color(0xFFB45309),
          fontWeight: FontWeight.w800,
          fontSize: 11,
        ),
      ),
    );
  }
}

class _KnowledgeArticlePager extends StatelessWidget {
  const _KnowledgeArticlePager({
    required this.page,
    required this.pageCount,
    required this.pageSize,
    required this.filteredCount,
    required this.onPageChanged,
  });

  final int page;
  final int pageCount;
  final int pageSize;
  final int filteredCount;
  final ValueChanged<int> onPageChanged;

  @override
  Widget build(BuildContext context) {
    final start = filteredCount == 0 ? 0 : ((page - 1) * pageSize) + 1;
    final end = (page * pageSize).clamp(0, filteredCount);
    final pages = _visiblePages(page, pageCount);

    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 720;
        return Wrap(
          spacing: 4,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          alignment: compact ? WrapAlignment.start : WrapAlignment.spaceBetween,
          children: [
            Text(
              'Showing $start to $end of $filteredCount articles',
              style: const TextStyle(
                color: DesignTokens.muted,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
            Wrap(
              spacing: 2,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                TextButton(
                  onPressed: page > 1 ? () => onPageChanged(page - 1) : null,
                  style: TextButton.styleFrom(
                    minimumSize: Size.zero,
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Previous'),
                ),
                for (final item in pages)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 2),
                    child: Material(
                      color: item == page ? DesignTokens.maroon : Colors.white,
                      borderRadius: BorderRadius.circular(8),
                      child: InkWell(
                        onTap: () => onPageChanged(item),
                        borderRadius: BorderRadius.circular(8),
                        child: Container(
                          width: 32,
                          height: 32,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(
                              color: item == page
                                  ? DesignTokens.maroon
                                  : DesignTokens.border,
                            ),
                          ),
                          child: Text(
                            '$item',
                            style: TextStyle(
                              color:
                                  item == page ? Colors.white : DesignTokens.ink,
                              fontWeight: FontWeight.w800,
                              fontSize: 12,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                TextButton(
                  onPressed: page < pageCount ? () => onPageChanged(page + 1) : null,
                  style: TextButton.styleFrom(
                    minimumSize: Size.zero,
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Next'),
                ),
              ],
            ),
          ],
        );
      },
    );
  }

  List<int> _visiblePages(int current, int total) {
    if (total <= 5) return [for (var i = 1; i <= total; i++) i];
    final start = (current - 2).clamp(1, total - 4);
    return [for (var i = start; i < start + 5; i++) i];
  }
}

class _KnowledgeCreateArticleDialog extends StatefulWidget {
  const _KnowledgeCreateArticleDialog({
    required this.service,
    this.lockOfficeTo,
  });

  final AdminArticleService service;
  final String? lockOfficeTo;

  @override
  State<_KnowledgeCreateArticleDialog> createState() =>
      _KnowledgeCreateArticleDialogState();
}

class _KnowledgeCreateArticleDialogState
    extends State<_KnowledgeCreateArticleDialog> {
  final _formKey = GlobalKey<FormState>();
  final _titleCtrl = TextEditingController();
  final _categoryCtrl = TextEditingController();
  final _summaryCtrl = TextEditingController();
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _titleCtrl.dispose();
    _categoryCtrl.dispose();
    _summaryCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final created = await widget.service.createArticle({
        'title': _titleCtrl.text.trim(),
        'category': _categoryCtrl.text.trim(),
        if (_summaryCtrl.text.trim().isNotEmpty)
          'summary': _summaryCtrl.text.trim(),
        'content': _summaryCtrl.text.trim(),
        'publish_status': false,
        if ((widget.lockOfficeTo ?? '').trim().isNotEmpty)
          'office': widget.lockOfficeTo!.trim(),
      });
      if (!mounted) return;
      Navigator.of(context).pop(created);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Create Article'),
      content: SizedBox(
        width: 460,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: _titleCtrl,
                decoration: const InputDecoration(
                  labelText: 'Title',
                  border: OutlineInputBorder(),
                ),
                validator: (value) =>
                    (value == null || value.trim().isEmpty) ? 'Enter a title.' : null,
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _categoryCtrl,
                decoration: const InputDecoration(
                  labelText: 'Category',
                  border: OutlineInputBorder(),
                ),
                validator: (value) => (value == null || value.trim().isEmpty)
                    ? 'Enter a category.'
                    : null,
              ),
              const SizedBox(height: 10),
              TextFormField(
                controller: _summaryCtrl,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'Summary',
                  helperText: 'Saved as a draft. You can finish the article next.',
                  border: OutlineInputBorder(),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(
                  _error!,
                  style: const TextStyle(
                    color: Color(0xFFB91C1C),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        ElevatedButton(
          onPressed: _saving ? null : _submit,
          style: ElevatedButton.styleFrom(
            backgroundColor: DesignTokens.maroon,
            foregroundColor: Colors.white,
          ),
          child: Text(_saving ? 'Creating...' : 'Create draft'),
        ),
      ],
    );
  }
}

String _formatArticleDate(String? raw) {
  final text = (raw ?? '').trim();
  if (text.isEmpty) return '—';
  final parsed = DateTime.tryParse(text)?.toLocal();
  if (parsed == null) return '—';
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  return '${months[parsed.month - 1]} ${parsed.day}, ${parsed.year}';
}
