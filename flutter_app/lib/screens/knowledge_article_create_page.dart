import 'package:flutter/material.dart';

import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../models/article_media_models.dart';
import '../services/admin_article_service.dart';
import '../services/file_pick.dart';
import '../widgets/article_attachments_panel.dart';
import '../widgets/article_html_codec.dart';
import '../widgets/article_rich_editor.dart';
import '../widgets/article_workspace_chrome.dart';
import '../widgets/sidebar.dart';
import 'admin_scaffold.dart';
import 'login_page.dart';
import 'office_scaffold.dart';

/// Full-page Knowledge Article creation for Admin and Office.
///
/// Reuses `POST /admin/kb/articles` plus pending `POST /admin/kb/media`.
class KnowledgeArticleCreatePage extends StatefulWidget {
  const KnowledgeArticleCreatePage({
    super.key,
    required this.service,
    this.knownCategories = const [],
    this.knownOffices = const [],
    this.debugCreateArticle,
    this.debugOfficeNames,
    this.debugUploadMedia,
    this.debugDeleteMedia,
    this.debugPickImage,
    this.debugPickFiles,
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

  @visibleForTesting
  final Future<ArticleMediaItem> Function({
    required PickedAppFile file,
    required String kind,
  })? debugUploadMedia;

  @visibleForTesting
  final Future<void> Function(String mediaId)? debugDeleteMedia;

  @visibleForTesting
  final Future<PickedAppFile?> Function()? debugPickImage;

  @visibleForTesting
  final Future<List<PickedAppFile>> Function()? debugPickFiles;

  @override
  State<KnowledgeArticleCreatePage> createState() =>
      _KnowledgeArticleCreatePageState();
}

class _KnowledgeArticleCreatePageState
    extends State<KnowledgeArticleCreatePage> {
  final _formKey = GlobalKey<FormState>();
  final _editorKey = GlobalKey<ArticleRichEditorState>();
  final _titleCtrl = TextEditingController();
  final _categoryCtrl = TextEditingController();
  final _summaryCtrl = TextEditingController();
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
  final List<ArticleMediaItem> _attachments = [];
  final Set<String> _pendingMediaIds = {};
  final Set<String> _uploadingIds = {};
  String? _attachmentError;

  @override
  void initState() {
    super.initState();
    _titleCtrl.addListener(_markDirty);
    _categoryCtrl.addListener(_markDirty);
    _summaryCtrl.addListener(_markDirty);
    _officeTextCtrl.addListener(_markDirty);
    WidgetsBinding.instance.addPostFrameCallback((_) => _bootstrapOffices());
  }

  @override
  void dispose() {
    if (!_saved) {
      _discardPendingMedia();
    }
    _titleCtrl.dispose();
    _categoryCtrl.dispose();
    _summaryCtrl.dispose();
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
      final fetched = await loadTicketOfficeNames(context);
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
    if (leave == true && !_saved) {
      await _discardPendingMedia();
    }
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
    if (articleBodyIsBlank(_editorValue.content)) {
      setState(() {
        _error = 'Enter article content.';
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
    final editor = _editorValue;
    final payload = <String, dynamic>{
      'title': _titleCtrl.text.trim(),
      'category': _categoryCtrl.text.trim(),
      if (_summaryCtrl.text.trim().isNotEmpty)
        'summary': _summaryCtrl.text.trim(),
      'content': editor.content,
      'content_format': editor.contentFormat,
      'publish_status': publish,
      if (office != null && office.isNotEmpty) 'office': office,
      if (_pendingMediaIds.isNotEmpty) 'media_ids': _pendingMediaIds.toList(),
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

  ArticleEditorValue get _editorValue {
    return _editorKey.currentState?.value ??
        const ArticleEditorValue(content: '', contentFormat: 'plain');
  }

  Map<String, String> _mediaHeaders() => AuthScope.of(context).ticketHeaders();

  Future<ArticleMediaItem> _uploadFile({
    required PickedAppFile file,
    required String kind,
  }) async {
    if (widget.debugUploadMedia != null) {
      return widget.debugUploadMedia!(file: file, kind: kind);
    }
    return widget.service.uploadArticleMedia(
      bytes: file.bytes,
      filename: file.name,
      kind: kind,
    );
  }

  Future<void> _deleteMediaId(String mediaId) async {
    try {
      if (widget.debugDeleteMedia != null) {
        await widget.debugDeleteMedia!(mediaId);
      } else {
        await widget.service.deleteArticleMedia(mediaId);
      }
    } catch (_) {}
  }

  Future<void> _discardPendingMedia() async {
    final ids = List<String>.from(_pendingMediaIds);
    _pendingMediaIds.clear();
    _attachments.clear();
    for (final id in ids) {
      await _deleteMediaId(id);
    }
  }

  Future<void> _uploadAttachments(List<PickedAppFile> files) async {
    setState(() => _attachmentError = null);
    for (final file in files) {
      if (file.bytes.length > articleAttachmentMaxBytes) {
        setState(() => _attachmentError = 'Files must be 10 MB or smaller.');
        continue;
      }
      final tempId = 'uploading-${file.name}-${file.bytes.length}';
      setState(() {
        _uploadingIds.add(tempId);
        _dirty = true;
      });
      try {
        final uploaded = await _uploadFile(file: file, kind: 'attachment');
        if (!mounted) return;
        setState(() {
          _attachments.add(uploaded);
          _pendingMediaIds.add(uploaded.id);
          _uploadingIds.remove(tempId);
          _dirty = true;
        });
      } catch (error) {
        if (!mounted) return;
        setState(() {
          _uploadingIds.remove(tempId);
          _attachmentError = error.toString();
        });
      }
    }
  }

  Future<ArticleMediaItem> _uploadInlineImage(PickedAppFile file) async {
    final uploaded = await _uploadFile(file: file, kind: 'inline_image');
    _pendingMediaIds.add(uploaded.id);
    _dirty = true;
    return uploaded;
  }

  Future<void> _removeAttachment(ArticleMediaItem item) async {
    await _deleteMediaId(item.id);
    if (!mounted) return;
    setState(() {
      _attachments.removeWhere((row) => row.id == item.id);
      _pendingMediaIds.remove(item.id);
      _dirty = true;
    });
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
                    ArticleWorkspaceHeader(
                      stacked: stacked,
                      onBack: _saving ? null : _handleBack,
                      breadcrumbCurrent: 'Create Article',
                      title: 'Create Knowledge Article',
                      subtitle:
                          'Share helpful information with students and staff. Save a draft now, or publish when the article should appear in the Knowledge Base.',
                      backButtonKey:
                          const Key('knowledge-article-create-back'),
                    ),
                    const SizedBox(height: 18),
                    if (stacked) ...[
                      _buildBasicInformation(),
                      const SizedBox(height: 14),
                      _buildContent(),
                      const SizedBox(height: 14),
                      _buildPublishSettings(),
                      const SizedBox(height: 14),
                      _buildAttachments(),
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
                                _buildAttachments(),
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
    return ArticleWorkspacePanel(
      title: 'Basic Information',
      subtitle: 'Provide the essential details about your article.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final stackFields = constraints.maxWidth < 560;
              final title = articleLabeledField(
                label: 'Title',
                required: true,
                child: TextFormField(
                  key: const Key('knowledge-article-create-title'),
                  controller: _titleCtrl,
                  enabled: !_saving,
                  decoration: articleInputDecoration(
                    hint: 'Enter a clear and descriptive title',
                  ),
                  validator: (value) => (value == null || value.trim().isEmpty)
                      ? 'Enter a title.'
                      : null,
                ),
              );
              final category = articleLabeledField(
                label: 'Category',
                required: true,
                helper: widget.knownCategories.isEmpty
                    ? null
                    : 'Use an existing category or enter a new one.',
                child: TextFormField(
                  key: const Key('knowledge-article-create-category'),
                  controller: _categoryCtrl,
                  enabled: !_saving,
                  decoration: articleInputDecoration(hint: 'Enter a category'),
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
              final office = articleLabeledField(
                label: 'Related Office',
                required: _isOffice,
                child: _buildOfficeField(),
              );
              final summary = articleLabeledField(
                label: 'Summary',
                helper: 'Optional short description shown in article lists.',
                child: TextFormField(
                  key: const Key('knowledge-article-create-summary'),
                  controller: _summaryCtrl,
                  enabled: !_saving,
                  minLines: 1,
                  maxLines: 3,
                  decoration: articleInputDecoration(
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
        decoration: articleInputDecoration(),
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
        decoration: articleInputDecoration(),
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
      decoration: articleInputDecoration(
        hint: 'Office name (optional)',
        helper: _officeFetchFailed
            ? 'Office list could not be loaded. You can still type an office name.'
            : 'Optional. Published articles can be scoped to an office.',
      ),
    );
  }

  Widget _buildContent() {
    return ArticleWorkspacePanel(
      title: 'Content',
      subtitle:
          'Write the full content of the article. Formatting, links, and images are saved with the article.',
      child: KeyedSubtree(
        key: const Key('knowledge-article-create-content'),
        child: ArticleRichEditor(
          key: _editorKey,
          initialContent: '',
          contentFormat: 'plain',
          enabled: !_saving,
          imageHeaders: _mediaHeaders(),
          debugPickImage: widget.debugPickImage,
          onChanged: (_) => _markDirty(),
          onUploadImage: _saving ? null : _uploadInlineImage,
        ),
      ),
    );
  }

  Widget _buildAttachments() {
    return ArticleWorkspacePanel(
      title: 'Attachments (optional)',
      subtitle:
          'Upload images or PDFs to support your article. Maximum 10 MB per file. Allowed: JPG, PNG, WebP, GIF, or PDF.',
      child: ArticleAttachmentsPanel(
        attachments: _attachments,
        uploading: _uploadingIds,
        enabled: !_saving,
        error: _attachmentError,
        showTitle: false,
        debugPickFiles: widget.debugPickFiles,
        onPick: _uploadAttachments,
        onDropped: _uploadAttachments,
        onRemove: _removeAttachment,
      ),
    );
  }

  Widget _buildPublishSettings() {
    return ArticleWorkspacePanel(
      title: 'Publish Settings',
      subtitle: 'Manage the status and visibility of this article.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          articleLabeledField(
            label: 'Status',
            child: DropdownButtonFormField<String>(
              key: const Key('knowledge-article-create-status'),
              value: _status,
              isExpanded: true,
              decoration: articleInputDecoration(),
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
