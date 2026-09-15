import 'dart:convert';

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../services/admin_article_service.dart';
import '../services/api_client.dart';
import '../widgets/sidebar.dart';
import 'admin_scaffold.dart';
import 'login_page.dart';
import 'office_scaffold.dart';

/// Full-page Knowledge Article creation for Admin and Office.
///
/// Reuses `POST /admin/kb/articles`. Does not invent tags, attachments,
/// rich-text toolbars, or a review/approval workflow.
class KnowledgeArticleCreatePage extends StatefulWidget {
  const KnowledgeArticleCreatePage({
    super.key,
    required this.service,
    this.knownCategories = const [],
    this.knownOffices = const [],
    this.debugCreateArticle,
    this.debugOfficeNames,
  });

  final AdminArticleService service;
  final List<String> knownCategories;
  final List<String> knownOffices;

  /// Intercepts `POST /admin/kb/articles` in widget tests.
  @visibleForTesting
  final Future<AdminArticle> Function(Map<String, dynamic> payload)?
      debugCreateArticle;

  /// Skips `GET /tickets/offices` in widget tests.
  @visibleForTesting
  final List<String>? debugOfficeNames;

  @override
  State<KnowledgeArticleCreatePage> createState() =>
      _KnowledgeArticleCreatePageState();
}

class _KnowledgeArticleCreatePageState
    extends State<KnowledgeArticleCreatePage> {
  final _formKey = GlobalKey<FormState>();
  final _titleCtrl = TextEditingController();
  final _categoryCtrl = TextEditingController();
  final _summaryCtrl = TextEditingController();
  final _contentCtrl = TextEditingController();
  final _officeTextCtrl = TextEditingController();

  bool _saving = false;
  bool _saved = false;
  bool _dirty = false;
  String? _error;
  String _status = 'draft';
  String? _pendingAction;
  String? _selectedOffice;
  List<String> _offices = [];
  bool _officeFetchFailed = false;

  @override
  void initState() {
    super.initState();
    _titleCtrl.addListener(_markDirty);
    _categoryCtrl.addListener(_markDirty);
    _summaryCtrl.addListener(_markDirty);
    _contentCtrl.addListener(_markDirty);
    _officeTextCtrl.addListener(_markDirty);
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrapOffices());
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    _categoryCtrl.dispose();
    _summaryCtrl.dispose();
    _contentCtrl.dispose();
    _officeTextCtrl.dispose();
    super.dispose();
  }

  void _markDirty() {
    if (_dirty || _saved || _saving) return;
    setState(() => _dirty = true);
  }

  bool get _isAdmin => AuthScope.of(context).role == 'admin';
  bool get _isOffice => AuthScope.of(context).role == 'office';

  String get _lockedOfficeName =>
      (AuthScope.of(context).currentUser?.officeName ?? '').trim();

  Future<void> _bootstrapOffices() async {
    if (!mounted || !_isAdmin) return;
    final seeded = <String>{
      ...widget.knownOffices.map((value) => value.trim()).where(
            (value) => value.isNotEmpty && value != 'All',
          ),
      ...(widget.debugOfficeNames ?? const []).map((value) => value.trim()),
    }..removeWhere((value) => value.isEmpty);
    final names = seeded.toList()..sort();
    setState(() {
      _offices = names;
      _officeFetchFailed = false;
    });
    if (widget.debugOfficeNames != null || widget.debugCreateArticle != null) {
      return;
    }
    try {
      final fetched = await _loadAdminOfficeNames(context);
      if (!mounted) return;
      final merged = {...names, ...fetched}.toList()..sort();
      setState(() {
        _offices = merged;
        _officeFetchFailed = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _officeFetchFailed = names.isEmpty);
    }
  }

  Future<bool> _confirmLeave() async {
    if (!_dirty || _saved || _saving) return true;
    final leave = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        key: const Key('knowledge-article-create-unsaved-dialog'),
        title: const Text('Discard unsaved article?'),
        content: const Text(
          'Your article has not been saved. Leave this page without creating it?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Stay'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Leave'),
          ),
        ],
      ),
    );
    return leave == true;
  }

  Future<void> _handleBack() async {
    if (!await _confirmLeave() || !mounted) return;
    Navigator.of(context).pop();
  }

  Future<void> _submit({required bool publish}) async {
    if (_saving) return;
    _error = null;
    if (!(_formKey.currentState?.validate() ?? false)) {
      setState(() {});
      return;
    }
    if (publish && _contentCtrl.text.trim().isEmpty) {
      setState(() {
        _error =
            'Article content is empty. Correct it and save as draft before publishing.';
      });
      return;
    }
    if (_isOffice && _lockedOfficeName.isEmpty) {
      setState(() {
        _error = 'Your account is not assigned to an office.';
      });
      return;
    }

    setState(() {
      _saving = true;
      _pendingAction = publish ? 'publish' : 'draft';
      _error = null;
    });

    final office = _resolvedOffice();
    final payload = <String, dynamic>{
      'title': _titleCtrl.text.trim(),
      'category': _categoryCtrl.text.trim(),
      if (_summaryCtrl.text.trim().isNotEmpty)
        'summary': _summaryCtrl.text.trim(),
      'content': _contentCtrl.text.trim(),
      'publish_status': publish,
      if (office != null && office.isNotEmpty) 'office': office,
    };

    try {
      final created = widget.debugCreateArticle != null
          ? await widget.debugCreateArticle!(payload)
          : await widget.service.createArticle(payload);
      if (!mounted) return;
      setState(() {
        _saved = true;
        _dirty = false;
      });
      Navigator.of(context).pop(created);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) {
        setState(() {
          _saving = false;
          _pendingAction = null;
        });
      }
    }
  }

  String? _resolvedOffice() {
    if (_isOffice) return _lockedOfficeName;
    if (_selectedOffice != null && _selectedOffice!.trim().isNotEmpty) {
      return _selectedOffice!.trim();
    }
    final typed = _officeTextCtrl.text.trim();
    return typed.isEmpty ? null : typed;
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
                  returnTo: (_) => KnowledgeArticleCreatePage(
                    service: widget.service,
                    knownCategories: widget.knownCategories,
                    knownOffices: widget.knownOffices,
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

    final body = PopScope(
      canPop: !_dirty || _saved,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;
        await _handleBack();
      },
      child: _buildWorkspace(),
    );

    if (_isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeKnowledgeArticles,
        title: 'Create Knowledge Article',
        description:
            'Share helpful information with students and staff.',
        fillBody: true,
        showHeader: false,
        child: body,
      );
    }

    return AdminScaffold(
      current: StudentNavItem.adminKnowledgeArticles,
      title: 'Create Knowledge Article',
      description:
          'Share helpful information with students and staff.',
      fillBody: true,
      showHeader: false,
      child: body,
    );
  }

  Widget _buildWorkspace() {
    return ColoredBox(
      color: DesignTokens.adminSurface,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 900;
          final stacked = constraints.maxWidth < 720;
          return SingleChildScrollView(
            key: const Key('knowledge-article-create-page'),
            padding: EdgeInsets.fromLTRB(
              wide ? 24 : 14,
              wide ? 20 : 14,
              wide ? 24 : 14,
              28,
            ),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1180),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _CreateArticleHeader(
                      stacked: stacked,
                      onBack: _saving ? null : _handleBack,
                    ),
                    const SizedBox(height: 18),
                    if (stacked) ...[
                      _buildBasicInformation(),
                      const SizedBox(height: 14),
                      _buildContent(),
                      const SizedBox(height: 14),
                      _buildPublishSettings(),
                      const SizedBox(height: 14),
                      _buildActions(),
                    ] else
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            flex: 7,
                            child: Column(
                              children: [
                                _buildBasicInformation(),
                                const SizedBox(height: 14),
                                _buildContent(),
                              ],
                            ),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            flex: 3,
                            child: Column(
                              children: [
                                _buildPublishSettings(),
                                const SizedBox(height: 14),
                                _buildActions(),
                              ],
                            ),
                          ),
                        ],
                      ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildBasicInformation() {
    return _CreatePanel(
      title: 'Basic Information',
      subtitle: 'Provide the essential details about your article.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final stackFields = constraints.maxWidth < 560;
              final title = _labeledField(
                label: 'Title',
                required: true,
                child: TextFormField(
                  key: const Key('knowledge-article-create-title'),
                  controller: _titleCtrl,
                  enabled: !_saving,
                  decoration: _inputDecoration(
                    hint: 'Enter a clear and descriptive title',
                  ),
                  validator: (value) => (value == null || value.trim().isEmpty)
                      ? 'Enter a title.'
                      : null,
                ),
              );
              final category = _labeledField(
                label: 'Category',
                required: true,
                helper: widget.knownCategories.isEmpty
                    ? null
                    : 'Use an existing category or enter a new one.',
                child: TextFormField(
                  key: const Key('knowledge-article-create-category'),
                  controller: _categoryCtrl,
                  enabled: !_saving,
                  decoration: _inputDecoration(hint: 'Enter a category'),
                  validator: (value) => (value == null || value.trim().isEmpty)
                      ? 'Enter a category.'
                      : null,
                ),
              );
              if (stackFields) {
                return Column(
                  children: [
                    title,
                    const SizedBox(height: 14),
                    category,
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: title),
                  const SizedBox(width: 14),
                  Expanded(child: category),
                ],
              );
            },
          ),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final stackFields = constraints.maxWidth < 560;
              final office = _labeledField(
                label: 'Related Office',
                required: _isOffice,
                child: _buildOfficeField(),
              );
              final summary = _labeledField(
                label: 'Summary',
                helper: 'Optional short description shown in article lists.',
                child: TextFormField(
                  key: const Key('knowledge-article-create-summary'),
                  controller: _summaryCtrl,
                  enabled: !_saving,
                  minLines: 1,
                  maxLines: 3,
                  decoration: _inputDecoration(
                    hint: 'Add a short summary (optional)',
                  ),
                ),
              );
              if (stackFields) {
                return Column(
                  children: [
                    office,
                    const SizedBox(height: 14),
                    summary,
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: office),
                  const SizedBox(width: 14),
                  Expanded(child: summary),
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _buildOfficeField() {
    if (_isOffice) {
      final name = _lockedOfficeName.isEmpty
          ? 'Not assigned'
          : _lockedOfficeName;
      return InputDecorator(
        key: const Key('knowledge-article-create-office'),
        decoration: _inputDecoration(),
        child: Row(
          children: [
            Expanded(
              child: Text(
                name,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
            ),
            const Icon(Icons.lock_outline, size: 16, color: DesignTokens.muted),
          ],
        ),
      );
    }

    if (_offices.isNotEmpty && !_officeFetchFailed) {
      final value = _selectedOffice != null && _offices.contains(_selectedOffice)
          ? _selectedOffice
          : null;
      return DropdownButtonFormField<String>(
        key: const Key('knowledge-article-create-office'),
        value: value,
        isExpanded: true,
        hint: const Text('Select office'),
        decoration: _inputDecoration(),
        items: [
          for (final office in _offices)
            DropdownMenuItem(
              value: office,
              child: Text(office, overflow: TextOverflow.ellipsis),
            ),
        ],
        onChanged: _saving
            ? null
            : (next) {
                setState(() {
                  _selectedOffice = next;
                  _dirty = true;
                });
              },
      );
    }

    return TextFormField(
      key: const Key('knowledge-article-create-office'),
      controller: _officeTextCtrl,
      enabled: !_saving,
      decoration: _inputDecoration(
        hint: 'Office name (optional)',
        helper: _officeFetchFailed
            ? 'Office list could not be loaded. You can still type an office name.'
            : 'Optional. Published articles can be scoped to an office.',
      ),
    );
  }

  Widget _buildContent() {
    return _CreatePanel(
      title: 'Content',
      subtitle:
          'Write the full content of the article. Articles are stored as plain text; the current editor does not include a formatting toolbar.',
      child: TextFormField(
        key: const Key('knowledge-article-create-content'),
        controller: _contentCtrl,
        enabled: !_saving,
        minLines: 10,
        maxLines: 18,
        decoration: _inputDecoration(
          hint: 'Start writing your article here…',
        ),
      ),
    );
  }

  Widget _buildPublishSettings() {
    return _CreatePanel(
      title: 'Publish Settings',
      subtitle: 'Manage the status and visibility of this article.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _labeledField(
            label: 'Status',
            child: DropdownButtonFormField<String>(
              key: const Key('knowledge-article-create-status'),
              value: _status,
              isExpanded: true,
              decoration: _inputDecoration(),
              items: const [
                DropdownMenuItem(value: 'draft', child: Text('Draft')),
                DropdownMenuItem(
                  value: 'published',
                  child: Text('Published'),
                ),
              ],
              onChanged: _saving
                  ? null
                  : (next) {
                      if (next == null) return;
                      setState(() {
                        _status = next;
                        _dirty = true;
                      });
                    },
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Save as draft or publish when ready.',
            style: TextStyle(
              color: DesignTokens.muted.withValues(alpha: 0.95),
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 12),
          Container(
            key: const Key('knowledge-article-create-publish-info'),
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
            decoration: BoxDecoration(
              color: const Color(0xFFEFF6FF),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFFBFDBFE)),
            ),
            child: const Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline, size: 18, color: Color(0xFF1D4ED8)),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Drafts stay in Knowledge Article until you publish. Published articles become visible in the public Knowledge Base. There is no administrator review step.',
                    style: TextStyle(
                      color: Color(0xFF1E3A8A),
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildActions() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_error != null) ...[
          Container(
            key: const Key('knowledge-article-create-error'),
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
            decoration: BoxDecoration(
              color: const Color(0xFFFEF2F2),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFFFECACA)),
            ),
            child: SelectableText(
              _error!,
              style: const TextStyle(
                color: Color(0xFFB91C1C),
                fontWeight: FontWeight.w700,
                fontSize: 13,
                height: 1.35,
              ),
            ),
          ),
          const SizedBox(height: 12),
        ],
        LayoutBuilder(
          builder: (context, constraints) {
            final stack = constraints.maxWidth < 420;
            final draft = OutlinedButton(
              key: const Key('knowledge-article-create-save-draft'),
              onPressed: _saving ? null : () => _submit(publish: false),
              style: OutlinedButton.styleFrom(
                foregroundColor: DesignTokens.maroon,
                side: const BorderSide(color: DesignTokens.maroon),
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: _pendingAction == 'draft'
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: DesignTokens.maroon,
                      ),
                    )
                  : const Text(
                      'Save as draft',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
            );
            final publish = ElevatedButton(
              key: const Key('knowledge-article-create-publish'),
              onPressed: _saving ? null : () => _submit(publish: true),
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: _pendingAction == 'publish'
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Text(
                      'Publish Article',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
            );
            if (stack) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  draft,
                  const SizedBox(height: 10),
                  publish,
                ],
              );
            }
            return Row(
              children: [
                Expanded(child: draft),
                const SizedBox(width: 10),
                Expanded(child: publish),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _CreateArticleHeader extends StatelessWidget {
  const _CreateArticleHeader({
    required this.stacked,
    required this.onBack,
  });

  final bool stacked;
  final VoidCallback? onBack;

  @override
  Widget build(BuildContext context) {
    final copy = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text.rich(
          TextSpan(
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
            children: [
              const TextSpan(text: 'Knowledge Base'),
              TextSpan(
                text: '  >  ',
                style: TextStyle(
                  color: DesignTokens.muted.withValues(alpha: 0.7),
                ),
              ),
              const TextSpan(
                text: 'Create Article',
                style: TextStyle(color: DesignTokens.ink),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        const Text(
          'Create Knowledge Article',
          style: TextStyle(
            color: DesignTokens.ink,
            fontSize: 28,
            fontWeight: FontWeight.w900,
            height: 1.1,
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'Share helpful information with students and staff. Save a draft now, or publish when the article should appear in the Knowledge Base.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 13,
            fontWeight: FontWeight.w600,
            height: 1.35,
          ),
        ),
      ],
    );
    final back = TextButton.icon(
      key: const Key('knowledge-article-create-back'),
      onPressed: onBack,
      icon: const Icon(Icons.arrow_back, size: 18),
      label: const Text(
        'Back to Articles',
        style: TextStyle(fontWeight: FontWeight.w800),
      ),
      style: TextButton.styleFrom(
        foregroundColor: DesignTokens.ink,
        backgroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: const BorderSide(color: DesignTokens.border),
        ),
      ),
    );

    if (stacked) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          copy,
          const SizedBox(height: 12),
          Align(alignment: Alignment.centerLeft, child: back),
        ],
      );
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(child: copy),
        const SizedBox(width: 12),
        back,
      ],
    );
  }
}

class _CreatePanel extends StatelessWidget {
  const _CreatePanel({
    required this.title,
    required this.subtitle,
    required this.child,
  });

  final String title;
  final String subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

Widget _labeledField({
  required String label,
  required Widget child,
  bool required = false,
  String? helper,
}) {
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Row(
        children: [
          Text(
            label,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontSize: 13,
              fontWeight: FontWeight.w800,
            ),
          ),
          if (required)
            const Text(
              ' *',
              style: TextStyle(
                color: DesignTokens.maroon,
                fontSize: 13,
                fontWeight: FontWeight.w800,
              ),
            ),
        ],
      ),
      const SizedBox(height: 6),
      child,
      if (helper != null) ...[
        const SizedBox(height: 6),
        Text(
          helper,
          style: const TextStyle(
            color: DesignTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    ],
  );
}

InputDecoration _inputDecoration({
  String? hint,
  String? helper,
}) {
  return InputDecoration(
    hintText: hint,
    helperText: helper,
    isDense: true,
    filled: true,
    fillColor: const Color(0xFFF8FAFC),
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
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
      borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.2),
    ),
  );
}

Future<List<String>> _loadAdminOfficeNames(BuildContext context) async {
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}/tickets/offices',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final decoded = result.json;
  Map<String, dynamic> data;
  if (decoded is Map<String, dynamic>) {
    data = decoded;
  } else if (decoded is Map) {
    data = Map<String, dynamic>.from(decoded);
  } else {
    try {
      final parsed = jsonDecode(result.body);
      data = parsed is Map
          ? Map<String, dynamic>.from(parsed)
          : <String, dynamic>{};
    } catch (_) {
      data = <String, dynamic>{};
    }
  }
  if (!result.ok) {
    throw StateError('Could not load offices.');
  }
  final items = data['items'] is List ? data['items'] as List : const [];
  final names = items
      .whereType<Map>()
      .map((item) => (item['name'] ?? '').toString().trim())
      .where((name) => name.isNotEmpty)
      .toSet()
      .toList()
    ..sort();
  return names;
}
