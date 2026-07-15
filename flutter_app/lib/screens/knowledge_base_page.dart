import 'dart:convert';
import 'dart:html' as html;

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../widgets/public_site_header.dart';
import '../widgets/source_pdf_viewer.dart';
import '../widgets/student_ui.dart';
import 'chatbot_page.dart';
import 'student_home.dart';

const _articleFontFamily = 'Inter';

class KnowledgeBasePage extends StatefulWidget {
  final String? initialCategory;
  final String? initialQuery;

  const KnowledgeBasePage({
    super.key,
    this.initialCategory,
    this.initialQuery,
  });

  @override
  State<KnowledgeBasePage> createState() => _KnowledgeBasePageState();
}

class _KnowledgeBasePageState extends State<KnowledgeBasePage> {
  final TextEditingController _searchController = TextEditingController();
  List<_KbArticle> _articles = [];
  List<_KbCategory> _categories = [];
  List<String> _suggestions = [];
  bool _loading = true;
  String? _error;
  String _activeQuery = '';
  String? _activeCategory;

  @override
  void initState() {
    super.initState();
    final initialQuery = widget.initialQuery?.trim() ?? '';
    if (initialQuery.isNotEmpty) {
      _searchController.text = initialQuery;
      _activeQuery = initialQuery;
    }
    final initialCategory = widget.initialCategory?.trim();
    if (initialCategory != null && initialCategory.isNotEmpty) {
      _activeCategory = initialCategory;
    }
    _loadInitialData();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadInitialData() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final data = await _getJson('/kb/categories');
      if (!mounted) {
        return;
      }
      setState(() {
        _categories = _categoryItems(data);
        _loading = false;
      });
      final shouldLoadArticles =
          (_activeQuery.isNotEmpty) || (_activeCategory != null);
      if (shouldLoadArticles) {
        await _loadArticles(query: _activeQuery, category: _activeCategory);
      } else {
        setState(() {
          _articles = [];
          _suggestions = [];
        });
      }
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _error =
            'Could not load Knowledge Base articles. Check your configured backend URL.';
        _loading = false;
      });
    }
  }

  Future<void> _loadArticles({String? query, String? category}) async {
    final nextQuery = (query ?? _activeQuery).trim();
    final nextCategory = category == null ? _activeCategory : category.trim();
    setState(() {
      _loading = true;
      _error = null;
      _activeQuery = nextQuery;
      _activeCategory =
          nextCategory == null || nextCategory.isEmpty ? null : nextCategory;
    });

    final params = <String, String>{
      'limit': '48',
      if (nextQuery.isNotEmpty) 'q': nextQuery,
      if (_activeCategory != null) 'category': _activeCategory!,
    };
    final queryString = Uri(queryParameters: params).query;

    try {
      final data = await _getJson('/kb/articles?$queryString');
      if (!mounted) {
        return;
      }
      setState(() {
        _articles = _articleItems(data);
        _suggestions = _suggestionItems(data);
        _loading = false;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _error = 'Could not search Knowledge Base articles.';
        _loading = false;
      });
    }
  }

  Future<Map<String, dynamic>> _getJson(String path) async {
    final request = html.HttpRequest();
    request.open('GET', '${AppConfig.resolvedApiBase}$path');
    request.send();
    await request.onLoadEnd.first;

    if (request.status != 200) {
      throw StateError('Request failed with status ${request.status}');
    }
    final decoded = jsonDecode(request.responseText ?? '{}');
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
  }

  void _performSearch([String? value]) {
    final query = (value ?? _searchController.text).trim();
    _searchController.text = query;
    _searchController.selection = TextSelection.collapsed(offset: query.length);
    if (query.isEmpty) {
      _showCategoryBrowse();
      return;
    }
    _loadArticles(query: query, category: '');
  }

  void _selectCategory(String? category) {
    _searchController.clear();
    _loadArticles(query: '', category: category ?? '');
  }

  void _showCategoryBrowse() {
    _searchController.clear();
    setState(() {
      _activeQuery = '';
      _activeCategory = null;
      _articles = [];
      _suggestions = [];
    });
    // Always re-fetch so newly published articles appear after admin work.
    _loadInitialData();
  }

  void _openArticle(_KbArticle article) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => _ArticleReaderPage(
          apiBase: AppConfig.resolvedApiBase,
          article: article,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final body = _KnowledgeBaseBody(
      searchController: _searchController,
      articles: _articles,
      categories: _categories,
      suggestions: _suggestions,
      loading: _loading,
      error: _error,
      activeQuery: _activeQuery,
      activeCategory: _activeCategory,
      onSearch: _performSearch,
      onRetry: _loadInitialData,
      onSelectCategory: _selectCategory,
      onShowCategories: _showCategoryBrowse,
      onOpenArticle: _openArticle,
      onGoHome: () {
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(builder: (_) => const StudentHomePage()),
          (route) => false,
        );
      },
    );

    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          const PublicSiteHeader(knowledgeBaseActive: true),
          Expanded(
            child: SingleChildScrollView(
              child: body,
            ),
          ),
        ],
      ),
    );
  }
}

class _KnowledgeBaseBody extends StatelessWidget {
  final TextEditingController searchController;
  final List<_KbArticle> articles;
  final List<_KbCategory> categories;
  final List<String> suggestions;
  final bool loading;
  final String? error;
  final String activeQuery;
  final String? activeCategory;
  final ValueChanged<String?> onSearch;
  final VoidCallback onRetry;
  final ValueChanged<String?> onSelectCategory;
  final VoidCallback onShowCategories;
  final ValueChanged<_KbArticle> onOpenArticle;
  final VoidCallback onGoHome;

  const _KnowledgeBaseBody({
    required this.searchController,
    required this.articles,
    required this.categories,
    required this.suggestions,
    required this.loading,
    required this.error,
    required this.activeQuery,
    required this.activeCategory,
    required this.onSearch,
    required this.onRetry,
    required this.onSelectCategory,
    required this.onShowCategories,
    required this.onOpenArticle,
    required this.onGoHome,
  });

  @override
  Widget build(BuildContext context) {
    final browsingCategory =
        activeCategory != null && activeCategory!.trim().isNotEmpty;

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 980),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 48),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (!browsingCategory || activeQuery.isNotEmpty) ...[
                _HeroSearch(
                  controller: searchController,
                  activeQuery: activeQuery,
                  onSearch: onSearch,
                ),
                const SizedBox(height: 28),
              ],
              if (activeQuery.isEmpty && activeCategory == null)
                _CategorySections(
                  categories: categories,
                  loading: loading,
                  error: error,
                  onRetry: onRetry,
                  onSelectCategory: onSelectCategory,
                )
              else if (browsingCategory && activeQuery.isEmpty)
                _CategoryHelpCenterView(
                  categoryName: activeCategory!,
                  articles: articles,
                  loading: loading,
                  error: error,
                  onRetry: onRetry,
                  onGoHome: onGoHome,
                  onBrowseCategories: onShowCategories,
                  onOpenArticle: onOpenArticle,
                  searchController: searchController,
                  onSearch: onSearch,
                )
              else
                _ArticleResults(
                  articles: articles,
                  suggestions: suggestions,
                  loading: loading,
                  error: error,
                  activeQuery: activeQuery,
                  activeCategory: activeCategory,
                  onRetry: onRetry,
                  onShowCategories: onShowCategories,
                  onOpenArticle: onOpenArticle,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CategoryHelpCenterView extends StatelessWidget {
  final String categoryName;
  final List<_KbArticle> articles;
  final bool loading;
  final String? error;
  final VoidCallback onRetry;
  final VoidCallback onGoHome;
  final VoidCallback onBrowseCategories;
  final ValueChanged<_KbArticle> onOpenArticle;
  final TextEditingController searchController;
  final ValueChanged<String?> onSearch;

  const _CategoryHelpCenterView({
    required this.categoryName,
    required this.articles,
    required this.loading,
    required this.error,
    required this.onRetry,
    required this.onGoHome,
    required this.onBrowseCategories,
    required this.onOpenArticle,
    required this.searchController,
    required this.onSearch,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            onPressed: onGoHome,
            style: TextButton.styleFrom(
              foregroundColor: DesignTokens.ink,
              padding: EdgeInsets.zero,
            ),
            child: const Text(
              'Home',
              style: TextStyle(
                decoration: TextDecoration.underline,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ),
        const SizedBox(height: 18),
        Center(
          child: Column(
            children: [
              Container(
                width: 54,
                height: 54,
                decoration: BoxDecoration(
                  color: DesignTokens.maroon.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: const Icon(
                  Icons.menu_book_rounded,
                  color: DesignTokens.maroon,
                  size: 28,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                categoryName,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 36,
                  fontWeight: FontWeight.w900,
                  color: DesignTokens.ink,
                  height: 1.15,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Browse published articles in this category',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 15,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 22),
        Container(
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(
            color: const Color(0xFFF8FAFC),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: const Color(0xFFE5E7EB)),
          ),
          child: Row(
            children: [
              const SizedBox(width: 12),
              const Icon(Icons.search_rounded, color: DesignTokens.muted),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                  controller: searchController,
                  onSubmitted: onSearch,
                  decoration: const InputDecoration(
                    hintText: 'Search',
                    border: InputBorder.none,
                    isDense: true,
                  ),
                ),
              ),
              IconButton(
                onPressed: () => onSearch(null),
                icon: const Icon(Icons.arrow_forward_rounded,
                    color: DesignTokens.maroon),
              ),
            ],
          ),
        ),
        const SizedBox(height: 28),
        const Divider(height: 1, color: Color(0xFFE5E7EB)),
        const SizedBox(height: 18),
        if (loading)
          const _LoadingState()
        else if (error != null)
          _ErrorState(message: error!, onRetry: onRetry)
        else if (articles.isEmpty)
          const Text(
            'No published articles in this category yet.',
            textAlign: TextAlign.center,
            style: TextStyle(color: DesignTokens.muted),
          )
        else
          LayoutBuilder(
            builder: (context, constraints) {
              final twoCol = constraints.maxWidth >= 720;
              final gap = 14.0;
              final width = twoCol
                  ? (constraints.maxWidth - gap) / 2
                  : constraints.maxWidth;
              return Wrap(
                spacing: gap,
                runSpacing: gap,
                children: articles.map((article) {
                  return SizedBox(
                    width: width,
                    child: _HelpCenterArticleTile(
                      title: article.title,
                      onTap: () => onOpenArticle(article),
                    ),
                  );
                }).toList(),
              );
            },
          ),
        const SizedBox(height: 20),
        Align(
          alignment: Alignment.center,
          child: TextButton(
            onPressed: onBrowseCategories,
            child: const Text('Browse all categories'),
          ),
        ),
      ],
    );
  }
}

class _HelpCenterArticleTile extends StatelessWidget {
  final String title;
  final VoidCallback onTap;

  const _HelpCenterArticleTile({
    required this.title,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xFF5C0A0F),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 18),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                    height: 1.3,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              const Icon(Icons.expand_more_rounded, color: Colors.white),
            ],
          ),
        ),
      ),
    );
  }
}

class _HeroSearch extends StatelessWidget {
  final TextEditingController controller;
  final String activeQuery;
  final ValueChanged<String?> onSearch;

  const _HeroSearch({
    required this.controller,
    required this.activeQuery,
    required this.onSearch,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(24, 32, 24, 28),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Colors.white, Color(0xFFFFFBF0)],
        ),
        border: Border.all(color: const Color(0xFFF1E4C8)),
        boxShadow: DesignTokens.softShadow(0.07),
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
            decoration: BoxDecoration(
              color: DesignTokens.maroon.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(999),
            ),
            child: const Text(
              'ASKa-Piyu Knowledge Base',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: DesignTokens.maroon,
              ),
            ),
          ),
          const SizedBox(height: 18),
          const Text(
            'Find student support topics',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 34,
              height: 1.12,
              fontWeight: FontWeight.w900,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 10),
          const Text(
            'Browse published articles by category, or search titles and summaries.',
            textAlign: TextAlign.center,
            style: TextStyle(
                fontSize: 16, height: 1.45, color: DesignTokens.muted),
          ),
          const SizedBox(height: 24),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Container(
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: const Color(0xFFE2E8F0)),
                boxShadow: DesignTokens.softShadow(0.08),
              ),
              child: Row(
                children: [
                  const SizedBox(width: 10),
                  const Icon(Icons.search_rounded, color: DesignTokens.muted),
                  const SizedBox(width: 10),
                  Expanded(
                    child: TextField(
                      controller: controller,
                      onSubmitted: onSearch,
                      decoration: const InputDecoration(
                        hintText: 'Search articles, policies, offices...',
                        border: InputBorder.none,
                        isDense: true,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  if (activeQuery.isNotEmpty)
                    IconButton(
                      tooltip: 'Clear search',
                      onPressed: () {
                        controller.clear();
                        onSearch('');
                      },
                      icon: const Icon(
                        Icons.close_rounded,
                        color: DesignTokens.muted,
                      ),
                    ),
                  SizedBox(
                    height: 46,
                    child: ElevatedButton(
                      onPressed: () => onSearch(null),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: DesignTokens.maroon,
                        foregroundColor: Colors.white,
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14),
                        ),
                      ),
                      child: const Text('Search'),
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (activeQuery.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text(
              'Showing results for "$activeQuery"',
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w800,
                color: DesignTokens.maroon,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ArticleResults extends StatelessWidget {
  final List<_KbArticle> articles;
  final List<String> suggestions;
  final bool loading;
  final String? error;
  final String activeQuery;
  final String? activeCategory;
  final VoidCallback onRetry;
  final VoidCallback onShowCategories;
  final ValueChanged<_KbArticle> onOpenArticle;

  const _ArticleResults({
    required this.articles,
    required this.suggestions,
    required this.loading,
    required this.error,
    required this.activeQuery,
    required this.activeCategory,
    required this.onRetry,
    required this.onShowCategories,
    required this.onOpenArticle,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: StudentSectionTitle(
                  title: activeCategory == null
                      ? 'Search Results'
                      : activeCategory!,
                  subtitle: activeCategory == null
                      ? 'Matching published Knowledge Base articles.'
                      : 'Published articles under this category.',
                ),
              ),
              TextButton.icon(
                onPressed: onShowCategories,
                icon: const Icon(Icons.grid_view_rounded, size: 18),
                label: const Text('Categories'),
                style: TextButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (loading)
            const _LoadingState()
          else if (error != null)
            _ErrorState(message: error!, onRetry: onRetry)
          else if (articles.isEmpty)
            _EmptyState(suggestions: suggestions)
          else
            ...articles.map(
              (article) => _ArticleCard(
                article: article,
                // Category heading already names the group; only show the
                // category chip in ungrouped search results.
                showCategoryChip: activeCategory == null,
                onTap: () => onOpenArticle(article),
              ),
            ),
        ],
      ),
    );
  }
}

class _CategorySections extends StatefulWidget {
  final List<_KbCategory> categories;
  final bool loading;
  final String? error;
  final VoidCallback onRetry;
  final ValueChanged<String?> onSelectCategory;

  const _CategorySections({
    required this.categories,
    required this.loading,
    required this.error,
    required this.onRetry,
    required this.onSelectCategory,
  });

  @override
  State<_CategorySections> createState() => _CategorySectionsState();
}

class _CategorySectionsState extends State<_CategorySections> {
  final Set<String> _expanded = {};

  @override
  Widget build(BuildContext context) {
    final visible = widget.categories
        .where((category) => category.articleCount > 0)
        .toList()
      ..sort((left, right) =>
          _categorySortKey(left.name).compareTo(_categorySortKey(right.name)));

    return StudentPanel(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StudentSectionTitle(
            title: 'Browse by Category',
            subtitle: 'Start with student-friendly sections, then open the focused articles you need.',
          ),
          const SizedBox(height: 16),
          if (widget.loading)
            const _LoadingState()
          else if (widget.error != null)
            _ErrorState(message: widget.error!, onRetry: widget.onRetry)
          else if (visible.isEmpty)
            const _EmptyCategoryState()
          else
            LayoutBuilder(
              builder: (context, constraints) {
                final twoColumns = constraints.maxWidth >= 860;
                final cardWidth = twoColumns
                    ? (constraints.maxWidth - 14) / 2
                    : constraints.maxWidth;
                return Wrap(
                  spacing: 14,
                  runSpacing: 14,
                  children: visible
                      .map(
                        (category) => SizedBox(
                          width: cardWidth,
                          child: _CategoryCard(
                            category: category,
                            expanded: _expanded.contains(category.name),
                            onToggle: () => _toggle(category.name),
                            onOpen: () =>
                                widget.onSelectCategory(category.name),
                          ),
                        ),
                      )
                      .toList(),
                );
              },
            ),
        ],
      ),
    );
  }

  void _toggle(String name) {
    setState(() {
      if (!_expanded.add(name)) {
        _expanded.remove(name);
      }
    });
  }
}

class _CategoryCard extends StatelessWidget {
  final _KbCategory category;
  final bool expanded;
  final VoidCallback onToggle;
  final VoidCallback onOpen;

  const _CategoryCard({
    required this.category,
    required this.expanded,
    required this.onToggle,
    required this.onOpen,
  });

  @override
  Widget build(BuildContext context) {
    final topics = category.visibleSubcategories;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: expanded
              ? DesignTokens.maroon.withValues(alpha: 0.22)
              : DesignTokens.border,
        ),
        boxShadow: DesignTokens.softShadow(expanded ? 0.08 : 0.04),
      ),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(18),
        child: Column(
          children: [
            InkWell(
              onTap: onOpen,
              borderRadius: BorderRadius.circular(18),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    StudentIconBox(
                      icon: _categoryIcon(category.name),
                      color: DesignTokens.maroon,
                      size: 44,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            category.name,
                            style: const TextStyle(
                              fontSize: 17,
                              height: 1.25,
                              fontWeight: FontWeight.w900,
                              color: DesignTokens.ink,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            '${category.articleCount} focused ${category.articleCount == 1 ? 'article' : 'articles'}',
                            style: const TextStyle(
                              fontSize: 12.5,
                              fontWeight: FontWeight.w700,
                              color: DesignTokens.muted,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      tooltip: expanded ? 'Collapse' : 'Preview topics',
                      onPressed: onToggle,
                      icon: Icon(
                        expanded
                            ? Icons.expand_less_rounded
                            : Icons.expand_more_rounded,
                        color: DesignTokens.maroon,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            if (expanded) ...[
              const Divider(height: 1, color: DesignTokens.border),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: topics
                          .map<Widget>(
                            (topic) => _TopicChip(
                              label: topic.name,
                              articleCount: topic.articleCount,
                            ),
                          )
                          .toList(),
                    ),
                    const SizedBox(height: 14),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: ElevatedButton.icon(
                        onPressed: onOpen,
                        icon: const Icon(Icons.arrow_forward_rounded, size: 18),
                        label: const Text('View articles'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: DesignTokens.maroon,
                          foregroundColor: Colors.white,
                          elevation: 0,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _TopicChip extends StatelessWidget {
  final String label;
  final int articleCount;

  const _TopicChip({required this.label, required this.articleCount});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
      decoration: BoxDecoration(
        color: DesignTokens.gold.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: DesignTokens.gold.withValues(alpha: 0.26)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          if (articleCount > 0) ...[
            const SizedBox(width: 6),
            Text(
              '$articleCount',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w900,
                color: DesignTokens.maroon,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ArticleCard extends StatelessWidget {
  final _KbArticle article;
  final bool showCategoryChip;
  final VoidCallback onTap;

  const _ArticleCard({
    required this.article,
    required this.onTap,
    this.showCategoryChip = true,
  });

  @override
  Widget build(BuildContext context) {
    final path = article.path.trim();
    final category = article.category.trim();
    final showPath = path.isNotEmpty &&
        path != category &&
        !_pathRepeatsCategoryOnly(path, category);

    return StudentInkCard(
      onTap: onTap,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      shadow: false,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const StudentIconBox(
                icon: Icons.description_outlined,
                color: DesignTokens.maroon,
                size: 42,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      article.title,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w900,
                        color: DesignTokens.ink,
                      ),
                    ),
                    if (showPath) ...[
                      const SizedBox(height: 5),
                      Text(
                        path,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 12,
                          height: 1.35,
                          color: DesignTokens.muted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded,
                  color: DesignTokens.muted),
            ],
          ),
          if (article.preview.trim().isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              article.preview,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                  fontSize: 13, height: 1.45, color: DesignTokens.ink),
            ),
          ],
          const SizedBox(height: 12),
          _ArticleMeta(
            article: article,
            showCategoryChip: showCategoryChip,
          ),
        ],
      ),
    );
  }
}

class _ArticleMeta extends StatelessWidget {
  final _KbArticle article;
  final bool showCategoryChip;

  const _ArticleMeta({
    required this.article,
    this.showCategoryChip = true,
  });

  @override
  Widget build(BuildContext context) {
    final chips = <Widget>[];
    final seen = <String>{};

    void addChip(IconData icon, String? label) {
      final value = (label ?? '').trim();
      if (value.isEmpty) return;
      final key = value.toLowerCase();
      if (!seen.add(key)) return;
      chips.add(_MetaChip(icon: icon, label: value));
    }

    if (showCategoryChip) {
      addChip(Icons.folder_outlined, article.category);
    }
    addChip(Icons.menu_book_outlined, _sourceLabel(article));
    addChip(Icons.apartment_outlined, article.office);
    addChip(Icons.label_outline_rounded, _documentTypeChipLabel(article));
    if (article.page != null) {
      addChip(Icons.bookmark_border_rounded, 'Page ${article.page}');
    }
    if (article.matchingSections > 1) {
      addChip(
        Icons.segment_rounded,
        '${article.matchingSections} matching sections',
      );
    }

    if (chips.isEmpty) return const SizedBox.shrink();
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: chips,
    );
  }
}

class _MetaChip extends StatelessWidget {
  final IconData icon;
  final String label;

  const _MetaChip({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: DesignTokens.muted),
          const SizedBox(width: 5),
          Text(
            label,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w800,
              color: DesignTokens.muted,
            ),
          ),
        ],
      ),
    );
  }
}

class _ArticleReaderPage extends StatelessWidget {
  final String apiBase;
  final _KbArticle article;

  const _ArticleReaderPage({
    super.key,
    required this.apiBase,
    required this.article,
  });

  Future<_KbArticleDetail> _loadDetail() async {
    final request = html.HttpRequest();
    request.open(
        'GET', '$apiBase/kb/articles/${Uri.encodeComponent(article.id)}');
    request.send();
    await request.onLoadEnd.first;
    if (request.status != 200) {
      throw StateError('Unable to load article detail');
    }
    final decoded = jsonDecode(request.responseText ?? '{}');
    return _KbArticleDetail.fromJson(Map<String, dynamic>.from(decoded as Map));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: Column(
        children: [
          const PublicSiteHeader(knowledgeBaseActive: true),
          Expanded(
            child: FutureBuilder<_KbArticleDetail>(
              future: _loadDetail(),
              builder: (context, snapshot) {
                return SingleChildScrollView(
                  child: _ArticleReaderBody(
                    article: article,
                    detail: snapshot.data,
                    loading: snapshot.connectionState != ConnectionState.done,
                    error: snapshot.hasError,
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _ArticleReaderBody extends StatelessWidget {
  final _KbArticle article;
  final _KbArticleDetail? detail;
  final bool loading;
  final bool error;

  const _ArticleReaderBody({
    required this.article,
    required this.detail,
    required this.loading,
    required this.error,
  });

  @override
  Widget build(BuildContext context) {
    final loaded = detail;
    final displayArticle = loaded?.article ?? article;

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 820),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 28, 24, 56),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(),
                style: TextButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                  padding: EdgeInsets.zero,
                ),
                child: const Text(
                  '← Back',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                displayArticle.category,
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: DesignTokens.muted,
                ),
              ),
              const SizedBox(height: 18),
              if (loading)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 80),
                  child: _LoadingState(),
                )
              else if (error || loaded == null)
                _ErrorState(
                  message: 'Could not load this article.',
                  onRetry: () => Navigator.of(context).pop(),
                )
              else
                _ArticleDocument(detail: loaded),
            ],
          ),
        ),
      ),
    );
  }
}

class _ArticleDocument extends StatelessWidget {
  final _KbArticleDetail detail;

  const _ArticleDocument({required this.detail});

  @override
  Widget build(BuildContext context) {
    final blocks = _formatArticleBlocks(detail.content);
    final modified = _formatModifiedOn(detail.updatedAt ?? detail.publishedAt);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Text(
                detail.title,
                style: const TextStyle(
                  fontFamily: _articleFontFamily,
                  fontSize: 34,
                  height: 1.2,
                  fontWeight: FontWeight.w800,
                  color: Color(0xFF5C0A0F),
                ),
              ),
            ),
            const SizedBox(width: 12),
            TextButton.icon(
              onPressed: () => html.window.print(),
              icon: const Icon(Icons.print_outlined, size: 18),
              label: const Text('Print'),
              style: TextButton.styleFrom(
                foregroundColor: DesignTokens.maroon,
              ),
            ),
          ],
        ),
        if (modified != null) ...[
          const SizedBox(height: 8),
          Text(
            'Modified on: $modified',
            style: const TextStyle(
              fontSize: 13,
              color: DesignTokens.muted,
            ),
          ),
        ],
        const SizedBox(height: 16),
        const Divider(height: 1, color: Color(0xFFE5E7EB)),
        const SizedBox(height: 26),
        if (detail.summary.trim().isNotEmpty) ...[
          Text(
            detail.summary.trim(),
            style: const TextStyle(
              fontFamily: _articleFontFamily,
              fontSize: 16,
              height: 1.65,
              fontStyle: FontStyle.italic,
              color: Color(0xFF475569),
            ),
          ),
          const SizedBox(height: 28),
        ],
        if (blocks.isEmpty)
          const Text(
            'No content available.',
            style: TextStyle(
              fontFamily: _articleFontFamily,
              fontSize: 16,
              height: 1.7,
              color: DesignTokens.muted,
            ),
          )
        else
          ...blocks.map((block) => _ArticleBlockView(block: block)),
        const SizedBox(height: 36),
        const Divider(height: 1, color: Color(0xFFE5E7EB)),
        const SizedBox(height: 20),
        _ArticleSourceFooter(article: detail.article),
        const SizedBox(height: 24),
        const _AskPanel(),
      ],
    );
  }
}

String? _formatModifiedOn(String? raw) {
  final value = (raw ?? '').trim();
  if (value.isEmpty) return null;
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return value;
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
  const weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  final local = parsed.toLocal();
  final weekday = weekdays[local.weekday - 1];
  final month = months[local.month - 1];
  final hour24 = local.hour;
  final hour12 = hour24 % 12 == 0 ? 12 : hour24 % 12;
  final ampm = hour24 >= 12 ? 'PM' : 'AM';
  final minute = local.minute.toString().padLeft(2, '0');
  return '$weekday, ${local.day} $month, ${local.year} at $hour12:$minute $ampm';
}

class _ArticleSourceFooter extends StatelessWidget {
  final _KbArticle article;

  const _ArticleSourceFooter({required this.article});

  @override
  Widget build(BuildContext context) {
    final sourceDoc = (article.sourceLabel ?? '').trim().isNotEmpty
        ? article.sourceLabel!.trim()
        : (article.sourceFilename.trim().isNotEmpty
            ? article.sourceFilename.trim()
            : 'Not specified');
    final section = (article.sourceSection ?? '').trim();
    final canView = (article.sourceViewUrl ?? '').trim().isNotEmpty &&
        (article.documentId ?? '').trim().isNotEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Source',
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w800,
            color: Color(0xFF5C0A0F),
          ),
        ),
        const SizedBox(height: 10),
        Text(
          'Source document: $sourceDoc',
          style: const TextStyle(fontSize: 13, height: 1.5, color: DesignTokens.muted),
        ),
        if (section.isNotEmpty)
          Text(
            'Source section: $section',
            style: const TextStyle(fontSize: 13, height: 1.5, color: DesignTokens.muted),
          ),
        Text(
          article.page == null
              ? 'Page: Not specified'
              : 'Page: ${article.page}',
          style: const TextStyle(fontSize: 13, height: 1.5, color: DesignTokens.muted),
        ),
        if (canView) ...[
          const SizedBox(height: 12),
          TextButton.icon(
            onPressed: () => showSourcePdfViewer(
              context,
              title: article.title,
              sourceLabel: sourceDoc,
              sourceSection: section,
              page: article.page,
              viewUrl: article.sourceViewUrl,
              pageUrl: article.sourcePageUrl,
            ),
            icon: const Icon(Icons.picture_as_pdf_outlined, size: 18),
            label: const Text('View Source'),
            style: TextButton.styleFrom(
              foregroundColor: DesignTokens.maroon,
              padding: EdgeInsets.zero,
            ),
          ),
        ],
      ],
    );
  }
}

class _AskPanel extends StatelessWidget {
  const _AskPanel();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 20),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE5E7EB)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Still have questions?',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'ASKa-Piyu can explain this article in simpler student-friendly language.',
            style: TextStyle(fontSize: 14, height: 1.5, color: DesignTokens.muted),
          ),
          const SizedBox(height: 14),
          SizedBox(
            height: 42,
            child: ElevatedButton.icon(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const ChatbotPage()),
              ),
              icon: const Icon(Icons.chat_bubble_outline_rounded, size: 18),
              label: const Text('Ask ASKa-Piyu'),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF5C0A0F),
                foregroundColor: Colors.white,
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ArticleBlockView extends StatelessWidget {
  final _ArticleBlock block;

  const _ArticleBlockView({required this.block});

  @override
  Widget build(BuildContext context) {
    switch (block.kind) {
      case _ArticleBlockKind.heading:
        return Padding(
          padding: const EdgeInsets.only(top: 22, bottom: 10),
          child: Text(
            block.text,
            style: const TextStyle(
              fontFamily: _articleFontFamily,
              fontSize: 22,
              height: 1.3,
              fontWeight: FontWeight.w800,
              color: Color(0xFF5C0A0F),
            ),
          ),
        );
      case _ArticleBlockKind.subheading:
        return Padding(
          padding: const EdgeInsets.only(top: 18, bottom: 8),
          child: Text(
            block.text,
            style: const TextStyle(
              fontFamily: _articleFontFamily,
              fontSize: 18,
              height: 1.35,
              fontWeight: FontWeight.w700,
              color: Color(0xFF5C0A0F),
            ),
          ),
        );
      case _ArticleBlockKind.fieldLabel:
        return Padding(
          padding: const EdgeInsets.only(top: 18, bottom: 4),
          child: Text(
            block.text,
            style: const TextStyle(
              fontFamily: _articleFontFamily,
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: DesignTokens.muted,
            ),
          ),
        );
      case _ArticleBlockKind.fieldValue:
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Text(
            block.text,
            style: const TextStyle(
              fontFamily: _articleFontFamily,
              fontSize: 22,
              height: 1.35,
              fontWeight: FontWeight.w800,
              color: Color(0xFF5C0A0F),
            ),
          ),
        );
      case _ArticleBlockKind.requirement:
        return Padding(
          padding: const EdgeInsets.only(bottom: 14, left: 2),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Icon(Icons.circle, size: 7, color: Color(0xFF5C0A0F)),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text.rich(
                      TextSpan(
                        style: const TextStyle(
                          fontFamily: _articleFontFamily,
                          fontSize: 16,
                          height: 1.5,
                          color: Color(0xFF5C0A0F),
                        ),
                        children: [
                          const TextSpan(
                            text: 'Requirement: ',
                            style: TextStyle(fontWeight: FontWeight.w800),
                          ),
                          TextSpan(
                            text: block.text,
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ],
                      ),
                    ),
                    if ((block.marker ?? '').trim().isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        'Where to Secure: ${block.marker}',
                        style: const TextStyle(
                          fontFamily: _articleFontFamily,
                          fontSize: 14,
                          height: 1.45,
                          color: DesignTokens.muted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        );
      case _ArticleBlockKind.numbered:
        return _ListBlock(prefix: block.marker ?? '', text: block.text);
      case _ArticleBlockKind.bullet:
        return _ListBlock(prefix: '', text: block.text, bullet: true);
      case _ArticleBlockKind.note:
        return Container(
          width: double.infinity,
          margin: const EdgeInsets.symmetric(vertical: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: const Color(0xFFFFF7ED),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFFFED7AA)),
          ),
          child: Text(
            block.text,
            style: const TextStyle(
              fontFamily: _articleFontFamily,
              fontSize: 14,
              height: 1.6,
              color: DesignTokens.ink,
            ),
          ),
        );
      case _ArticleBlockKind.paragraph:
        return Padding(
          padding: const EdgeInsets.only(bottom: 14),
          child: Text(
            block.text,
            style: const TextStyle(
              fontFamily: _articleFontFamily,
              fontSize: 16,
              height: 1.7,
              color: Color(0xFF334155),
            ),
          ),
        );
    }
  }
}

class _ListBlock extends StatelessWidget {
  final String prefix;
  final String text;
  final bool bullet;

  const _ListBlock({
    required this.prefix,
    required this.text,
    this.bullet = false,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            constraints: const BoxConstraints(minWidth: 26),
            padding: const EdgeInsets.only(top: 8),
            child: bullet
                ? Container(
                    width: 6,
                    height: 6,
                    decoration: const BoxDecoration(
                      color: Color(0xFF5C0A0F),
                      shape: BoxShape.circle,
                    ),
                  )
                : Text(
                    prefix,
                    style: const TextStyle(
                      fontFamily: _articleFontFamily,
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: Color(0xFF5C0A0F),
                    ),
                  ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontFamily: _articleFontFamily,
                fontSize: 16,
                height: 1.65,
                color: Color(0xFF334155),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

enum _ArticleBlockKind {
  heading,
  subheading,
  fieldLabel,
  fieldValue,
  requirement,
  paragraph,
  numbered,
  bullet,
  note,
}

class _ArticleBlock {
  final _ArticleBlockKind kind;
  final String text;
  final String? marker;

  const _ArticleBlock(this.kind, this.text, {this.marker});
}

const _fieldSectionHeadings = {
  'office / division',
  'office',
  'classification',
  'type of transaction',
  'fees',
  'total processing time',
  'processing time',
};

const _valueAfterHeading = {
  'who may avail',
  'office / division',
  'office',
  'classification',
  'type of transaction',
  'fees',
  'total processing time',
  'processing time',
};

const _majorSectionHeadings = {
  'overview',
  'who may avail',
  'requirements',
  'checklist of requirements',
  'process',
  'process / steps',
  'client steps',
  'agency actions',
  'important notes',
  'notes',
  'key points',
  'important reminders',
  'eligibility / conditions',
  'details',
  'purpose',
  'when to use',
  'how to fill out',
  'instructions',
  'instructions / how to submit',
  'how to submit',
  'related service / office',
  'source',
};

List<_ArticleBlock> _formatArticleBlocks(String content) {
  final normalized = content
      .replaceAll('\r\n', '\n')
      .replaceAll(RegExp(r'[ \t]+'), ' ')
      .trim();
  if (normalized.isEmpty) {
    return [];
  }

  final lines = normalized
      .split('\n')
      .map((line) => line.trim())
      .where((line) => line.isNotEmpty)
      .toList();
  final blocks = <_ArticleBlock>[];

  for (var i = 0; i < lines.length; i++) {
    final line = lines[i];
    if (_isPageMarker(line)) {
      continue;
    }

    final headingKey = line.replaceAll(RegExp(r'[:：]\s*$'), '').trim().toLowerCase();

    if (_fieldSectionHeadings.contains(headingKey) ||
        _majorSectionHeadings.contains(headingKey)) {
      if (_fieldSectionHeadings.contains(headingKey)) {
        blocks.add(_ArticleBlock(
          _ArticleBlockKind.fieldLabel,
          _titleCase(headingKey),
        ));
      } else {
        blocks.add(_ArticleBlock(
          _ArticleBlockKind.heading,
          _titleCase(headingKey),
        ));
      }
      if (_valueAfterHeading.contains(headingKey) && i + 1 < lines.length) {
        final next = lines[i + 1];
        final nextKey =
            next.replaceAll(RegExp(r'[:：]\s*$'), '').trim().toLowerCase();
        if (!_fieldSectionHeadings.contains(nextKey) &&
            !_majorSectionHeadings.contains(nextKey) &&
            !_isPageMarker(next) &&
            !RegExp(r'^(?:[-•*]\s*)?Requirement:', caseSensitive: false)
                .hasMatch(next)) {
          blocks.add(_ArticleBlock(_ArticleBlockKind.fieldValue, next));
          i++;
        }
      }
      continue;
    }

    final requirement = RegExp(
      r'^(?:[-•*]\s*)?Requirement:\s*(.+)$',
      caseSensitive: false,
    ).firstMatch(line);
    if (requirement != null) {
      String? where;
      if (i + 1 < lines.length) {
        final whereMatch = RegExp(
          r'^(?:[-•*]\s*)?Where to Secure:\s*(.+)$',
          caseSensitive: false,
        ).firstMatch(lines[i + 1]);
        if (whereMatch != null) {
          where = whereMatch.group(1)!.trim();
          i++;
        }
      }
      blocks.add(_ArticleBlock(
        _ArticleBlockKind.requirement,
        requirement.group(1)!.trim(),
        marker: where,
      ));
      continue;
    }

    final whereOnly = RegExp(
      r'^(?:[-•*]\s*)?Where to Secure:\s*(.+)$',
      caseSensitive: false,
    ).firstMatch(line);
    if (whereOnly != null) {
      blocks.add(_ArticleBlock(
        _ArticleBlockKind.paragraph,
        'Where to Secure: ${whereOnly.group(1)!.trim()}',
      ));
      continue;
    }

    final section = _parseSectionLine(line);
    if (section != null) {
      blocks.add(_ArticleBlock(
        _ArticleBlockKind.heading,
        '${section.label} ${section.title}'.trim(),
      ));
      if (section.paragraph != null && section.paragraph!.isNotEmpty) {
        blocks.add(
            _ArticleBlock(_ArticleBlockKind.paragraph, section.paragraph!));
      }
      continue;
    }

    final numbered =
        RegExp(r'^(\d+[\).]|[a-zA-Z][\).])\s+(.+)$').firstMatch(line);
    final bullet = RegExp(r'^([\u2022\-*])\s+(.+)$').firstMatch(line);

    if (numbered != null) {
      blocks.add(_ArticleBlock(
        _ArticleBlockKind.numbered,
        numbered.group(2)!.trim(),
        marker: numbered.group(1),
      ));
    } else if (bullet != null) {
      blocks.add(
          _ArticleBlock(_ArticleBlockKind.bullet, bullet.group(2)!.trim()));
    } else if (_isMajorHeading(line)) {
      blocks.add(_ArticleBlock(_ArticleBlockKind.heading, _cleanHeading(line)));
    } else if (_isSubheading(line)) {
      blocks.add(
          _ArticleBlock(_ArticleBlockKind.subheading, _cleanHeading(line)));
    } else if (_isNote(line)) {
      blocks.add(_ArticleBlock(_ArticleBlockKind.note, line));
    } else {
      blocks.add(_ArticleBlock(_ArticleBlockKind.paragraph, line));
    }
  }

  return blocks;
}

bool _isPageMarker(String line) {
  final value = line.trim();
  return RegExp(r'^-+\s*page\s+\d+\s*-+$', caseSensitive: false)
          .hasMatch(value) ||
      RegExp(r'^page\s+\d+$', caseSensitive: false).hasMatch(value);
}

class _ParsedSectionLine {
  final String label;
  final String title;
  final String? paragraph;

  const _ParsedSectionLine({
    required this.label,
    required this.title,
    required this.paragraph,
  });
}

_ParsedSectionLine? _parseSectionLine(String line) {
  final cleaned = line.replaceAll(RegExp(r'\s+'), ' ').trim();
  final match = RegExp(
    r'^(section|chapter|article|sec\.?)\s+([IVXLCDM]+|\d+|[A-Z])(?:\s*[·:\-]\s*|\s+)(.+)$',
    caseSensitive: false,
  ).firstMatch(cleaned);
  if (match == null) {
    return null;
  }

  final rawKind = match.group(1)!.replaceAll('.', '').toUpperCase();
  final kind = rawKind == 'SEC' ? 'SEC' : rawKind;
  final number = match.group(2)!.toUpperCase();
  final rest = match.group(3)!.trim();
  final split = _splitTitleAndParagraph(rest);
  return _ParsedSectionLine(
    label: '$kind $number',
    title: split.title,
    paragraph: split.paragraph,
  );
}

class _TitleParagraphSplit {
  final String title;
  final String? paragraph;

  const _TitleParagraphSplit({required this.title, required this.paragraph});
}

_TitleParagraphSplit _splitTitleAndParagraph(String value) {
  final words = value.split(' ').where((word) => word.isNotEmpty).toList();
  if (words.isEmpty) {
    return const _TitleParagraphSplit(title: '', paragraph: null);
  }

  var titleEnd = words.length;
  for (var index = 0; index < words.length; index++) {
    final word = words[index].replaceAll(RegExp(r'[^A-Za-z]'), '');
    if (word.isEmpty) {
      continue;
    }
    final startsNormalSentence = word[0].toUpperCase() == word[0] &&
        word.substring(1) != word.substring(1).toUpperCase();
    if (index > 0 && startsNormalSentence) {
      titleEnd = index;
      break;
    }
  }

  final rawTitle = words.take(titleEnd).join(' ').trim();
  final paragraph = words.skip(titleEnd).join(' ').trim();
  return _TitleParagraphSplit(
    title: _titleCase(rawTitle),
    paragraph: paragraph.isEmpty ? null : paragraph,
  );
}

bool _isMajorHeading(String line) {
  final value = line.trim();
  if (RegExp(r'^(section|chapter|article)\s+[\w.-]+[:\s-]',
          caseSensitive: false)
      .hasMatch(value)) {
    return true;
  }
  final letters = value.replaceAll(RegExp(r'[^A-Za-z]'), '');
  return value.length <= 80 &&
      letters.length >= 4 &&
      value == value.toUpperCase() &&
      !value.endsWith('.');
}

bool _isSubheading(String line) {
  final value = line.trim();
  if (isFormattedArticleSectionHeading(value)) {
    return true;
  }
  if (value.length > 70 || value.endsWith('.')) {
    return false;
  }
  final titleLike =
      RegExp(r'^[A-Z][A-Za-z]*(\s+[A-Z][A-Za-z]*){0,5}$').hasMatch(value);
  return RegExp(
              r'\b(policy|policies|requirements?|procedures?|eligibility|notes?|guidelines?|classification|curricular offerings|administrative officials|enrollment|admission|attendance|graduation|retention)\b',
              caseSensitive: false)
          .hasMatch(value) ||
      titleLike;
}

bool _isNote(String line) {
  return RegExp(r'^(note|important|reminder)\s*[:\-]', caseSensitive: false)
      .hasMatch(line.trim());
}

String _cleanHeading(String line) {
  final cleaned =
      line.replaceAll(RegExp(r'\s+'), ' ').trim().replaceAll(RegExp(r':$'), '');
  final structural = RegExp(
    r'^(section|chapter|article)\s+(.+)$',
    caseSensitive: false,
  ).firstMatch(cleaned);
  if (structural != null) {
    final label = structural.group(1)!.toLowerCase();
    final suffix = structural.group(2)!.trim();
    return '${label[0].toUpperCase()}${label.substring(1)} $suffix';
  }
  final letters = cleaned.replaceAll(RegExp(r'[^A-Za-z]'), '');
  if (letters.length >= 4 && cleaned == cleaned.toUpperCase()) {
    return _titleCase(cleaned);
  }
  return cleaned;
}

String _titleCase(String value) {
  const keepUpper = {'OSAS', 'TOR', 'ID', 'PDF'};
  return value.toLowerCase().split(' ').map((word) {
    final upper = word.toUpperCase();
    if (keepUpper.contains(upper)) {
      return upper;
    }
    if (word.isEmpty) {
      return word;
    }
    return '${word[0].toUpperCase()}${word.substring(1)}';
  }).join(' ');
}

class _LoadingState extends StatelessWidget {
  const _LoadingState();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.symmetric(vertical: 30),
        child: CircularProgressIndicator(color: DesignTokens.maroon),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final List<String> suggestions;

  const _EmptyState({this.suggestions = const []});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 34),
      child: Center(
        child: Column(
          children: [
            const Text(
              'No exact article found.',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w900,
                color: DesignTokens.ink,
              ),
            ),
            if (suggestions.isNotEmpty) ...[
              const SizedBox(height: 10),
              const Text(
                'Try:',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                  color: DesignTokens.muted,
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 8,
                runSpacing: 8,
                children: suggestions
                    .map<Widget>(
                      (suggestion) => _TopicChip(
                        label: suggestion,
                        articleCount: 0,
                      ),
                    )
                    .toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _EmptyCategoryState extends StatelessWidget {
  const _EmptyCategoryState();

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: 34),
      child: Center(
        child: Text(
          'No published Knowledge Base articles yet. Ask an administrator to publish reviewed articles first.',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: 14,
            fontWeight: FontWeight.w800,
            color: DesignTokens.muted,
          ),
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _ErrorState({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFFED7AA)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded, color: Color(0xFFC2410C)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(
                  fontSize: 13, height: 1.4, color: Color(0xFF9A3412)),
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

List<_KbCategory> _categoryItems(Map<String, dynamic> data) {
  final items = data['items'];
  if (items is! List) {
    return [];
  }
  return items
      .whereType<Map>()
      .map((item) => _KbCategory.fromJson(Map<String, dynamic>.from(item)))
      .where((category) => category.name.trim().isNotEmpty)
      .toList();
}

List<_KbArticle> _articleItems(Map<String, dynamic> data) {
  final items = data['items'];
  if (items is! List) {
    return [];
  }
  return items
      .whereType<Map>()
      .map((item) => _KbArticle.fromJson(Map<String, dynamic>.from(item)))
      .toList();
}

List<String> _suggestionItems(Map<String, dynamic> data) {
  final items = data['suggestions'];
  if (items is! List) {
    return [];
  }
  return items
      .map((item) => item.toString().trim())
      .where((item) => item.isNotEmpty)
      .toList();
}

String _sourceLabel(_KbArticle article) {
  final raw = article.sourceFilename.trim();
  if (raw.isNotEmpty) {
    final stem = raw
        .replaceAll(RegExp(r'\.[^.]+$'), '')
        .replaceAll(RegExp(r'[_\-]+'), ' ')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    final lower = stem.toLowerCase();
    if (lower.contains('handbook')) {
      return 'Student Handbook';
    }
    if (stem.isNotEmpty) {
      return stem;
    }
  }
  return _documentTypeChipLabel(article) ?? 'Source Document';
}

String? _documentTypeChipLabel(_KbArticle article) {
  final raw = article.documentType.trim().toLowerCase();
  if (raw.isEmpty) return null;
  switch (raw) {
    case 'procedure':
      return 'Procedure';
    case 'requirement':
      return 'Requirement / Form';
    case 'information':
      // Default type — skip to avoid cluttering every card.
      return null;
    default:
      if (raw.length == 1) return raw.toUpperCase();
      return '${raw[0].toUpperCase()}${raw.substring(1)}';
  }
}

bool _pathRepeatsCategoryOnly(String path, String category) {
  if (category.isEmpty) return false;
  final normalizedPath =
      path.toLowerCase().replaceAll(RegExp(r'\s*>\s*'), ' ').trim();
  final normalizedCategory = category.toLowerCase().trim();
  if (normalizedPath == normalizedCategory) return true;
  // Hide paths that are only "Category >" with nothing useful after.
  final parts = path
      .split('>')
      .map((part) => part.trim())
      .where((part) => part.isNotEmpty)
      .toList();
  return parts.length == 1 && parts.first.toLowerCase() == normalizedCategory;
}

IconData _categoryIcon(String name) {
  final value = name.toLowerCase();
  if (value.contains('admission')) {
    return Icons.how_to_reg_rounded;
  }
  if (value.contains('academic')) {
    return Icons.school_rounded;
  }
  if (value.contains('record')) {
    return Icons.folder_copy_rounded;
  }
  if (value.contains('scholarship') || value.contains('financial')) {
    return Icons.payments_rounded;
  }
  if (value.contains('program') || value.contains('curricular')) {
    return Icons.account_balance_rounded;
  }
  if (value.contains('service')) {
    return Icons.support_agent_rounded;
  }
  if (value.contains('administrative')) {
    return Icons.groups_rounded;
  }
  if (value.contains('technical')) {
    return Icons.computer_rounded;
  }
  if (value.contains('requirement') || value.contains('form')) {
    return Icons.assignment_rounded;
  }
  return Icons.menu_book_rounded;
}

int _categorySortKey(String name) {
  const order = [
    'Admissions',
    'Academic Policies',
    'Student Records',
    'Scholarships & Financial Policies',
    'Programs & Curricular Offerings',
    'Student Services',
    'Administrative Information',
    'Technical Support',
    'Requirements & Forms',
  ];
  final normalized = _normalizeDisplayText(name);
  final index = order.indexWhere((item) => _normalizeDisplayText(item) == normalized);
  return index == -1 ? 999 : index;
}

class _KbCategory {
  final String name;
  final int articleCount;
  final List<_KbSubcategory> subcategories;

  const _KbCategory({
    required this.name,
    required this.articleCount,
    required this.subcategories,
  });

  List<_KbSubcategory> get visibleSubcategories {
    final visible = subcategories
        .where((subcategory) => subcategory.articleCount > 0)
        .toList();
    if (visible.isNotEmpty) {
      return visible;
    }
    return subcategories.take(8).toList();
  }

  factory _KbCategory.fromJson(Map<String, dynamic> json) {
    final rawSubcategories = json['subcategories'];
    final subcategories = rawSubcategories is List
        ? rawSubcategories
            .whereType<Map>()
            .map((item) =>
                _KbSubcategory.fromJson(Map<String, dynamic>.from(item)))
            .where((item) => item.name.trim().isNotEmpty)
            .toList()
        : <_KbSubcategory>[];
    return _KbCategory(
      name: (json['name'] ?? 'General').toString(),
      articleCount: _intOrNull(json['article_count']) ??
          subcategories.fold<int>(
            0,
            (total, subcategory) => total + subcategory.articleCount,
          ),
      subcategories: subcategories,
    );
  }
}

class _KbSubcategory {
  final String name;
  final int articleCount;

  const _KbSubcategory({
    required this.name,
    required this.articleCount,
  });

  factory _KbSubcategory.fromJson(Map<String, dynamic> json) {
    return _KbSubcategory(
      name: _friendlyTopicTitle((json['name'] ?? '').toString()),
      articleCount: _intOrNull(json['article_count']) ?? 0,
    );
  }
}

class _KbArticle {
  final String id;
  final String title;
  final String originalTitle;
  final String path;
  final String category;
  final String subcategory;
  final String office;
  final String documentType;
  final int? page;
  final String sourceFilename;
  final String? sourceSection;
  final String? sourceLabel;
  final String? documentId;
  final String? sourceViewUrl;
  final String? sourcePageUrl;
  final String preview;
  final String summary;
  final int matchingSections;

  const _KbArticle({
    required this.id,
    required this.title,
    required this.originalTitle,
    required this.path,
    required this.category,
    required this.subcategory,
    required this.office,
    required this.documentType,
    required this.page,
    required this.sourceFilename,
    this.sourceSection,
    this.sourceLabel,
    this.documentId,
    this.sourceViewUrl,
    this.sourcePageUrl,
    required this.preview,
    required this.summary,
    required this.matchingSections,
  });

  factory _KbArticle.fromJson(Map<String, dynamic> json) {
    final rawTitle = (json['title'] ?? '').toString().trim();
    final category = (json['category'] ?? 'General').toString().trim();
    final subcategory = (json['subcategory'] ?? '').toString();
    final path = (json['path'] ?? '').toString();
    final summary = (json['summary'] ?? json['short_summary'] ?? '')
        .toString()
        .trim();
    final preview = summary.isNotEmpty
        ? summary
        : (json['content_preview'] ?? '').toString();
    return _KbArticle(
      id: (json['id'] ?? json['chunk_id'] ?? '').toString(),
      // Always prefer PostgreSQL article.title; never fall back to category.
      title: rawTitle.isEmpty ? 'Untitled Article' : rawTitle,
      originalTitle: rawTitle,
      path: path,
      category: category.isEmpty ? 'General' : category,
      subcategory: subcategory,
      office: (json['office'] ?? '').toString().trim(),
      documentType: (json['document_type'] ?? '').toString().trim(),
      page: _intOrNull(json['page_number'] ?? json['page']),
      sourceFilename: (json['source_filename'] ?? '').toString(),
      sourceSection: (json['source_section'] ?? '').toString().trim().isEmpty
          ? null
          : (json['source_section'] ?? '').toString().trim(),
      sourceLabel: (json['source_label'] ?? json['source_document'] ?? '')
              .toString()
              .trim()
              .isEmpty
          ? null
          : (json['source_label'] ?? json['source_document'] ?? '')
              .toString()
              .trim(),
      documentId: (json['document_id'] ?? '').toString().trim().isEmpty
          ? null
          : (json['document_id'] ?? '').toString().trim(),
      sourceViewUrl: (json['source_view_url'] ?? '').toString().trim().isEmpty
          ? null
          : (json['source_view_url'] ?? '').toString().trim(),
      sourcePageUrl: (json['source_page_url'] ?? '').toString().trim().isEmpty
          ? null
          : (json['source_page_url'] ?? '').toString().trim(),
      preview: preview,
      summary: summary,
      matchingSections: _intOrNull(json['matching_sections']) ?? 1,
    );
  }
}

class _KbArticleDetail {
  final _KbArticle article;
  final String title;
  final String path;
  final String content;
  final String summary;
  final String? updatedAt;
  final String? publishedAt;

  const _KbArticleDetail({
    required this.article,
    required this.title,
    required this.path,
    required this.content,
    required this.summary,
    this.updatedAt,
    this.publishedAt,
  });

  factory _KbArticleDetail.fromJson(Map<String, dynamic> json) {
    final article = _KbArticle.fromJson(json);
    final updated = (json['updated_at'] ?? '').toString().trim();
    final published = (json['published_at'] ?? '').toString().trim();
    return _KbArticleDetail(
      article: article,
      title: article.title,
      path: article.path,
      content: (json['content'] ?? json['text'] ?? json['body'] ?? '').toString(),
      summary: (json['summary'] ?? json['short_summary'] ?? article.summary)
          .toString()
          .trim(),
      updatedAt: updated.isEmpty ? null : updated,
      publishedAt: published.isEmpty ? null : published,
    );
  }
}

String _friendlyTopicTitle(String value) {
  var cleaned = value
      .replaceAll(RegExp(r'\s+'), ' ')
      .replaceAll('petitionsubject', 'petition subject')
      .trim();
  if (cleaned.isEmpty) {
    return cleaned;
  }

  final mapped = _mappedFriendlyTitle(cleaned);
  if (mapped != null) {
    return mapped;
  }

  cleaned = cleaned
      .replaceFirst(RegExp(r'^\(+'), '')
      .replaceFirst(RegExp(r'\)+$'), '')
      .trim();
  final colonIndex = cleaned.indexOf(':');
  if (colonIndex >= 0 && colonIndex < cleaned.length - 1) {
    cleaned = cleaned.substring(colonIndex + 1).trim();
  }
  cleaned = cleaned
      .replaceFirst(
        RegExp(
          r'^(chapter|article|section|sec\.?)\s+([ivxlcdm]+|\d+|[a-z])\s*[-:.)]?\s*',
          caseSensitive: false,
        ),
        '',
      )
      .replaceAll(RegExp(r'\s*/\s*'), ' / ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();

  if (cleaned.length > 72) {
    final sentenceEnd = cleaned.indexOf(RegExp(r'[.;]'));
    if (sentenceEnd > 24) {
      cleaned = cleaned.substring(0, sentenceEnd).trim();
    }
  }

  return _titleCase(cleaned);
}

String? _mappedFriendlyTitle(String value) {
  final normalized = _normalizeDisplayText(value);
  final mappings = <String, String>{
    'a graduating student may request for unscheduled petition subject':
        'Unscheduled / Petition Subject',
    'unscheduled petition subject': 'Unscheduled / Petition Subject',
    'petition subject': 'Unscheduled / Petition Subject',
    'enhanced policies and guidelines': 'Enhanced Policies and Guidelines',
    'leave of absence': 'Leave of Absence Policy',
    'excuse slip': 'Excuse Slip',
    'scholastic delinquency': 'Scholastic Delinquency',
    'transcript of records': 'Transcript of Records',
    'certificate of registration': 'Certificate of Registration',
    'copy of grades': 'Copy of Grades',
    'good moral': 'Good Moral',
    'honorable dismissal': 'Honorable Dismissal',
  };
  for (final entry in mappings.entries) {
    if (normalized.contains(entry.key)) {
      return entry.value;
    }
  }
  return null;
}

String _normalizeDisplayText(String value) {
  return value
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
}

int? _intOrNull(Object? value) {
  if (value is int) {
    return value;
  }
  return int.tryParse((value ?? '').toString());
}
