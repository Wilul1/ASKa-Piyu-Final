import 'dart:html' as html;

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../services/admin_article_service.dart';
import '../widgets/admin_kb_article_shared.dart';
import '../widgets/admin_kb_article_widgets.dart';

String _formatLoadError(Object error) {
  if (error is AdminArticleRequestException) {
    return error.toString();
  }
  return error.toString();
}

String _friendlySourceLabel(String? raw) {
  final value = (raw ?? '').trim();
  if (value.isEmpty) return 'Not specified';
  final lower = value.toLowerCase();
  if (lower.contains('handbook')) return 'Student Handbook';
  if (lower.contains('charter') || lower.contains('citizen')) {
    return "Citizen's Charter";
  }
  return value
      .replaceAll(RegExp(r'\.[^.]+$'), '')
      .replaceAll(RegExp(r'[_\-]+'), ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
}

String _documentTypeLabel(AdminArticle article) {
  final raw = (article.documentType ??
          article.metadata['document_type']?.toString() ??
          '')
      .trim()
      .toLowerCase();
  if (raw.isEmpty) return 'Not specified';
  switch (raw) {
    case 'procedure':
      return 'Procedure';
    case 'requirement':
      return 'Requirement / Form';
    case 'information':
      return 'Information';
    default:
      return '${raw[0].toUpperCase()}${raw.substring(1)}';
  }
}

/// Collapsible article library for searching and managing all saved articles.
class AdminKbArticleLibrarySection extends StatefulWidget {
  const AdminKbArticleLibrarySection({
    super.key,
    required this.setAdminHeader,
    this.refreshToken = 0,
  });

  final void Function(html.HttpRequest request) setAdminHeader;
  final int refreshToken;

  @override
  State<AdminKbArticleLibrarySection> createState() =>
      _AdminKbArticleLibrarySectionState();
}

enum _StatusFilter { all, published, draft }

class _AdminKbArticleLibrarySectionState extends State<AdminKbArticleLibrarySection> {
  late final AdminArticleService _service = AdminArticleService(
    apiBase: AppConfig.resolvedApiBase,
    setAdminHeader: widget.setAdminHeader,
  );

  final TextEditingController _searchController = TextEditingController();
  bool _expanded = false;
  bool _loadedOnce = false;
  bool _bulkBusy = false;

  List<AdminArticle> _articles = [];
  bool _loading = false;
  String? _error;
  _StatusFilter _statusFilter = _StatusFilter.all;
  String? _sourceFilter;
  String? _categoryFilter;
  String? _documentTypeFilter;
  bool _needsReviewOnly = false;
  final Set<String> _selectedIds = {};

  @override
  void didUpdateWidget(covariant AdminKbArticleLibrarySection oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.refreshToken != oldWidget.refreshToken && _expanded) {
      _loadArticles();
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadArticles() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final articles = await _service.listArticles();
      if (!mounted) return;
      setState(() {
        _articles = articles;
        _loadedOnce = true;
        _selectedIds.removeWhere(
          (id) => !articles.any((article) => article.id == id),
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _formatLoadError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<String> get _sourceOptions {
    final values = _articles
        .map((article) => _friendlySourceLabel(article.sourceFilename))
        .where((value) => value != 'Not specified')
        .toSet()
        .toList()
      ..sort();
    return values;
  }

  List<String> get _categoryOptions {
    final values = _articles
        .map((article) => article.category.trim())
        .where((value) => value.isNotEmpty)
        .toSet()
        .toList()
      ..sort();
    return values;
  }

  List<String> get _documentTypeOptions {
    final values = _articles
        .map(_documentTypeLabel)
        .where((value) => value != 'Not specified')
        .toSet()
        .toList()
      ..sort();
    return values;
  }

  List<AdminArticle> get _filteredArticles {
    final query = _searchController.text.trim().toLowerCase();
    return _articles.where((article) {
      if (_statusFilter == _StatusFilter.published && !article.published) {
        return false;
      }
      if (_statusFilter == _StatusFilter.draft && article.published) {
        return false;
      }
      if (_needsReviewOnly && !article.needsReview && article.reviewReasons.isEmpty) {
        return false;
      }
      if (_sourceFilter != null &&
          _friendlySourceLabel(article.sourceFilename) != _sourceFilter) {
        return false;
      }
      if (_categoryFilter != null && article.category.trim() != _categoryFilter) {
        return false;
      }
      if (_documentTypeFilter != null &&
          _documentTypeLabel(article) != _documentTypeFilter) {
        return false;
      }
      if (query.isEmpty) return true;
      final haystack = [
        article.title,
        article.category,
        article.sourceSection ?? '',
        article.office ?? '',
        article.sourceFilename ?? '',
        _documentTypeLabel(article),
      ].join(' ').toLowerCase();
      return haystack.contains(query);
    }).toList();
  }

  Future<void> _publish(AdminArticle article) async {
    try {
      await _service.publishArticle(article.id);
      if (!mounted) return;
      showKbSnackBar(context, 'Published "${article.title}".');
      await _loadArticles();
    } catch (error) {
      if (!mounted) return;
      showKbSnackBar(context, error.toString());
    }
  }

  Future<void> _unpublish(AdminArticle article) async {
    try {
      await _service.unpublishArticle(article.id);
      if (!mounted) return;
      showKbSnackBar(context, 'Unpublished "${article.title}".');
      await _loadArticles();
    } catch (error) {
      if (!mounted) return;
      showKbSnackBar(context, error.toString());
    }
  }

  Future<void> _delete(AdminArticle article) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete article?'),
        content: Text(
          'Delete "${article.title}" permanently? This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text('Delete', style: TextStyle(color: Colors.red.shade700)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _service.deleteArticle(article.id);
      if (!mounted) return;
      setState(() => _selectedIds.remove(article.id));
      showKbSnackBar(context, 'Deleted "${article.title}".');
      await _loadArticles();
    } catch (error) {
      if (!mounted) return;
      showKbSnackBar(context, error.toString());
    }
  }

  Future<void> _edit(AdminArticle article) async {
    final saved = await showAdminArticleEditDialog(
      context: context,
      article: article,
      service: _service,
    );
    if (saved == true) {
      if (!mounted) return;
      showKbSnackBar(context, 'Article updated.');
      await _loadArticles();
    }
  }

  Future<void> _bulkPublishSelected() async {
    final drafts = _filteredArticles
        .where((article) => _selectedIds.contains(article.id) && !article.published)
        .toList();
    if (drafts.isEmpty) {
      showKbSnackBar(context, 'Select draft articles to publish.');
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Publish selected articles?'),
        content: Text(
          'You are about to publish ${drafts.length} articles to the public Knowledge Base. Published articles will be visible to students. Continue?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: DesignTokens.maroon,
              foregroundColor: Colors.white,
            ),
            child: const Text('Publish'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _bulkBusy = true);
    var success = 0;
    var failed = 0;
    try {
      for (final article in drafts) {
        try {
          await _service.publishArticle(article.id);
          success += 1;
        } catch (_) {
          failed += 1;
        }
      }
      if (!mounted) return;
      setState(() => _selectedIds.clear());
      showKbSnackBar(
        context,
        failed == 0
            ? '$success articles published to the Knowledge Base.'
            : '$success articles published. $failed failed.',
      );
      await _loadArticles();
    } finally {
      if (mounted) setState(() => _bulkBusy = false);
    }
  }

  Future<void> _bulkUnpublishSelected() async {
    final published = _filteredArticles
        .where((article) => _selectedIds.contains(article.id) && article.published)
        .toList();
    if (published.isEmpty) {
      showKbSnackBar(context, 'Select published articles to unpublish.');
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Unpublish selected articles?'),
        content: Text(
          'You are about to remove ${published.length} articles from the public Knowledge Base. They will remain saved as drafts. Continue?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: DesignTokens.maroon,
              foregroundColor: Colors.white,
            ),
            child: const Text('Unpublish'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _bulkBusy = true);
    try {
      final result = await _service.bulkUnpublish(
        published.map((article) => article.id).toList(),
      );
      if (!mounted) return;
      setState(() => _selectedIds.clear());
      final failureNote =
          result.failureCount > 0 ? ' ${result.failureCount} failed.' : '';
      showKbSnackBar(
        context,
        '${result.successCount} articles unpublished.$failureNote',
      );
      await _loadArticles();
    } catch (error) {
      if (!mounted) return;
      showKbSnackBar(context, error.toString());
    } finally {
      if (mounted) setState(() => _bulkBusy = false);
    }
  }

  Widget _dropdownFilter({
    required String label,
    required String? value,
    required List<String> options,
    required ValueChanged<String?> onChanged,
  }) {
    const allValue = '__all__';
    return SizedBox(
      width: 220,
      child: InputDecorator(
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
          isDense: true,
          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        ),
        child: DropdownButtonHideUnderline(
          child: DropdownButton<String>(
            isExpanded: true,
            value: value ?? allValue,
            items: [
              const DropdownMenuItem<String>(
                value: allValue,
                child: Text('All'),
              ),
              ...options.map(
                (option) => DropdownMenuItem<String>(
                  value: option,
                  child: Text(option, overflow: TextOverflow.ellipsis),
                ),
              ),
            ],
            onChanged: (selected) {
              if (selected == null || selected == allValue) {
                onChanged(null);
              } else {
                onChanged(selected);
              }
            },
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filteredArticles;
    final selectedCount = _selectedIds.length;
    final selectableIds = filtered.map((article) => article.id).toList();

    return KbAdminPanel(
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: const EdgeInsets.only(top: 12),
          title: const Text(
            'Article Library',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
          ),
          subtitle: const Text(
            'Filter, publish, unpublish, or delete saved articles. Unpublished articles stay as drafts and leave the public Knowledge Base.',
            style: TextStyle(fontSize: 12, color: DesignTokens.muted),
          ),
          onExpansionChanged: (expanded) {
            setState(() => _expanded = expanded);
            if (expanded && !_loadedOnce) {
              _loadArticles();
            }
          },
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ChoiceChip(
                  label: Text(
                    'All (${_articles.length})',
                  ),
                  selected: _statusFilter == _StatusFilter.all,
                  onSelected: (_) => setState(() => _statusFilter = _StatusFilter.all),
                  selectedColor: DesignTokens.maroon.withValues(alpha: 0.14),
                ),
                ChoiceChip(
                  label: Text(
                    'Published (${_articles.where((a) => a.published).length})',
                  ),
                  selected: _statusFilter == _StatusFilter.published,
                  onSelected: (_) =>
                      setState(() => _statusFilter = _StatusFilter.published),
                  selectedColor: DesignTokens.maroon.withValues(alpha: 0.14),
                ),
                ChoiceChip(
                  label: Text(
                    'Draft (${_articles.where((a) => !a.published).length})',
                  ),
                  selected: _statusFilter == _StatusFilter.draft,
                  onSelected: (_) =>
                      setState(() => _statusFilter = _StatusFilter.draft),
                  selectedColor: DesignTokens.maroon.withValues(alpha: 0.14),
                ),
                FilterChip(
                  label: const Text('Needs Review'),
                  selected: _needsReviewOnly,
                  onSelected: (value) => setState(() => _needsReviewOnly = value),
                  selectedColor: const Color(0xFFFFF7ED),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                _dropdownFilter(
                  label: 'Source document',
                  value: _sourceFilter,
                  options: _sourceOptions,
                  onChanged: (value) => setState(() => _sourceFilter = value),
                ),
                _dropdownFilter(
                  label: 'Category',
                  value: _categoryFilter,
                  options: _categoryOptions,
                  onChanged: (value) => setState(() => _categoryFilter = value),
                ),
                _dropdownFilter(
                  label: 'Document type',
                  value: _documentTypeFilter,
                  options: _documentTypeOptions,
                  onChanged: (value) =>
                      setState(() => _documentTypeFilter = value),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _searchController,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(
                labelText: 'Search articles',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  '$selectedCount selected',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                TextButton(
                  onPressed: selectableIds.isEmpty
                      ? null
                      : () => setState(() {
                            _selectedIds
                              ..clear()
                              ..addAll(selectableIds);
                          }),
                  child: const Text('Select All'),
                ),
                TextButton(
                  onPressed: selectedCount == 0
                      ? null
                      : () => setState(_selectedIds.clear),
                  child: const Text('Clear Selection'),
                ),
              ],
            ),
            if (selectedCount > 0) ...[
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFF8FAFC),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: DesignTokens.border),
                ),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ElevatedButton(
                      onPressed: _bulkBusy ? null : _bulkPublishSelected,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: DesignTokens.maroon,
                        foregroundColor: Colors.white,
                      ),
                      child: const Text('Publish Selected'),
                    ),
                    OutlinedButton(
                      onPressed: _bulkBusy ? null : _bulkUnpublishSelected,
                      child: const Text('Unpublish Selected'),
                    ),
                    TextButton(
                      onPressed:
                          _bulkBusy ? null : () => setState(_selectedIds.clear),
                      child: const Text('Clear Selection'),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 14),
            if (_loading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: CircularProgressIndicator(color: DesignTokens.maroon),
                ),
              )
            else if (_error != null)
              SelectableText(
                _error!,
                style: TextStyle(color: Colors.red.shade700, height: 1.5),
              )
            else if (filtered.isEmpty)
              Text(
                _articles.isEmpty
                    ? 'No saved articles yet. Generate candidates from an extracted document above.'
                    : 'No articles match this filter.',
                style: const TextStyle(color: DesignTokens.muted, height: 1.5),
              )
            else
              ...filtered.map(
                (article) => Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: AdminArticleCard(
                    article: article,
                    showCheckbox: true,
                    selected: _selectedIds.contains(article.id),
                    onSelectedChanged: (value) {
                      setState(() {
                        if (value) {
                          _selectedIds.add(article.id);
                        } else {
                          _selectedIds.remove(article.id);
                        }
                      });
                    },
                    showPublicReadinessLabels: true,
                    onView: () =>
                        showAdminArticleViewDialog(context, article, _service),
                    onEdit: () => _edit(article),
                    onPublish: () => _publish(article),
                    onUnpublish: () => _unpublish(article),
                    onDelete: () => _delete(article),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
