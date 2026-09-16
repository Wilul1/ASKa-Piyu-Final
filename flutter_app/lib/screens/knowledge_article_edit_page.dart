import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../models/article_media_models.dart';
import '../services/admin_article_service.dart';
import '../services/file_pick.dart';
import '../widgets/admin_kb_article_widgets.dart';
import '../widgets/article_attachments_panel.dart';
import '../widgets/article_html_codec.dart';
import '../widgets/article_rich_editor.dart';
import '../widgets/article_workspace_chrome.dart';
import '../widgets/sidebar.dart';
import 'admin_scaffold.dart';
import 'login_page.dart';
import 'office_scaffold.dart';

/// Full-page Knowledge Article editor for Admin and Office.
///
/// Visual shell matches [KnowledgeArticleCreatePage]. Save/publish/unpublish
/// still use the existing article endpoints.
class KnowledgeArticleEditPage extends StatefulWidget {
  const KnowledgeArticleEditPage({
    super.key,
    required this.articleId,
    required this.setAdminHeader,
    this.articleService,
    this.knownCategories = const [],
    this.knownOffices = const [],
    this.debugGetArticle,
    this.debugUpdateArticle,
    this.debugPublishArticle,
    this.debugUnpublishArticle,
    this.debugOfficeNames,
    this.debugUploadMedia,
    this.debugDeleteMedia,
    this.debugPickImage,
    this.debugPickFiles,
  });

  final String articleId;
  final void Function(Map<String, String> headers) setAdminHeader;
  final AdminArticleService? articleService;
  final List<String> knownCategories;
  final List<String> knownOffices;

  @visibleForTesting
  final Future<AdminArticle> Function(String id)? debugGetArticle;

  @visibleForTesting
  final Future<AdminArticle> Function(String id, Map<String, dynamic> payload)?
      debugUpdateArticle;

  @visibleForTesting
  final Future<void> Function(String id)? debugPublishArticle;

  @visibleForTesting
  final Future<void> Function(String id)? debugUnpublishArticle;

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
  State<KnowledgeArticleEditPage> createState() =>
      _KnowledgeArticleEditPageState();
}

class _KnowledgeArticleEditPageState extends State<KnowledgeArticleEditPage> {
  late final AdminArticleService _service = widget.articleService ??
      AdminArticleService(
        apiBase: AppConfig.resolvedApiBase,
        setAdminHeader: widget.setAdminHeader,
      );

  final _formKey = GlobalKey<FormState>();
  final _editorKey = GlobalKey<ArticleRichEditorState>();
  final _titleCtrl = TextEditingController();
  final _categoryCtrl = TextEditingController();
  final _summaryCtrl = TextEditingController();
  final _officeTextCtrl = TextEditingController();
  final _sourceCtrl = TextEditingController();
  final _sourceSectionCtrl = TextEditingController();

  AdminArticle? _article;
  Object? _loadError;
  bool _loading = true;
  bool _saving = false;
  bool _saved = false;
  bool _dirty = false;
  bool _statusChanged = false;
  String? _error;
  String? _pendingAction;
  String _audience = 'both';
  String? _selectedOffice;
  List<String> _offices = [];
  bool _officeFetchFailed = false;
  bool _published = false;
  final List<ArticleMediaItem> _attachments = [];
  final Set<String> _uploadingIds = {};
  String? _attachmentError;

  @override
  void initState() {
    super.initState();
    _titleCtrl.addListener(_markDirty);
    _categoryCtrl.addListener(_markDirty);
    _summaryCtrl.addListener(_markDirty);
    _officeTextCtrl.addListener(_markDirty);
    _sourceCtrl.addListener(_markDirty);
    _sourceSectionCtrl.addListener(_markDirty);
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    _categoryCtrl.dispose();
    _summaryCtrl.dispose();
    _officeTextCtrl.dispose();
    _sourceCtrl.dispose();
    _sourceSectionCtrl.dispose();
    super.dispose();
  }

  void _markDirty() {
    if (_loading || _dirty || _saved || _saving) return;
    setState(() => _dirty = true);
  }

  bool get _isAdmin => AuthScope.of(context).role == 'admin';
  bool get _isOffice => AuthScope.of(context).role == 'office';

  String get _lockedOfficeName =>
      (AuthScope.of(context).currentUser?.officeName ?? '').trim();

  ArticleEditorValue get _editorValue {
    final article = _article;
    return _editorKey.currentState?.value ??
        ArticleEditorValue(
          content: article?.displayContent ?? '',
          contentFormat: article?.contentFormat ?? 'plain',
        );
  }

  Future<void> _load() async {
    try {
      final article = widget.debugGetArticle != null
          ? await widget.debugGetArticle!(widget.articleId)
          : await _service.getArticle(widget.articleId);
      if (!mounted) return;
      _hydrate(article);
      setState(() {
        _loading = false;
        _loadError = null;
      });
      await _bootstrapOffices();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = error;
      });
    }
  }

  void _hydrate(AdminArticle article) {
    _article = article;
    _published = article.published;
    _audience = article.audience;
    _titleCtrl.text = article.title;
    _categoryCtrl.text = article.category;
    _summaryCtrl.text = buildShortSummary(
      article.summary,
      article.isHtmlContent
          ? articleHtmlToPlain(article.displayContent)
          : article.displayContent,
      title: article.title,
      documentType: article.documentType,
    );
    _officeTextCtrl.text = article.office ?? '';
    _selectedOffice = (article.office ?? '').trim().isEmpty
        ? null
        : article.office!.trim();
    _sourceCtrl.text = article.sourceFilename ?? '';
    _sourceSectionCtrl.text = article.sourceSection ?? '';
    _attachments
      ..clear()
      ..addAll(article.attachments.where((item) => item.isAttachment));
    if (_attachments.isEmpty) {
      _attachments.addAll(article.media.where((item) => item.isAttachment));
    }
    _dirty = false;
  }

  Future<void> _bootstrapOffices() async {
    if (!mounted || !_isAdmin) return;
    final seeded = <String>{
      ...widget.knownOffices.map((value) => value.trim()).where(
            (value) => value.isNotEmpty && value != 'All',
          ),
      ...(widget.debugOfficeNames ?? const []).map((value) => value.trim()),
      if ((_selectedOffice ?? '').isNotEmpty) _selectedOffice!,
    }..removeWhere((value) => value.isEmpty);
    final names = seeded.toList()..sort();
    setState(() {
      _offices = names;
      _officeFetchFailed = false;
    });
    if (widget.debugOfficeNames != null || widget.debugGetArticle != null) {
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
        key: const Key('knowledge-article-edit-unsaved-dialog'),
        title: const Text('Discard unsaved changes?'),
        content: const Text(
          'Your edits have not been saved. Leave this page without saving?',
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
    Navigator.of(context).pop(_saved || _statusChanged);
  }

  String? _resolvedOffice() {
    if (_isOffice) return _lockedOfficeName;
    if (_selectedOffice != null && _selectedOffice!.trim().isNotEmpty) {
      return _selectedOffice!.trim();
    }
    final typed = _officeTextCtrl.text.trim();
    return typed.isEmpty ? null : typed;
  }

  Map<String, String> _mediaHeaders() {
    try {
      return AuthScope.of(context).ticketHeaders();
    } catch (_) {
      return const {};
    }
  }

  Future<ArticleMediaItem> _uploadFile({
    required PickedAppFile file,
    required String kind,
  }) async {
    if (widget.debugUploadMedia != null) {
      return widget.debugUploadMedia!(file: file, kind: kind);
    }
    return _service.uploadArticleMedia(
      bytes: file.bytes,
      filename: file.name,
      kind: kind,
      articleId: widget.articleId,
    );
  }

  Future<void> _deleteMediaId(String mediaId) async {
    try {
      if (widget.debugDeleteMedia != null) {
        await widget.debugDeleteMedia!(mediaId);
      } else {
        await _service.deleteArticleMedia(mediaId);
      }
    } catch (error) {
      if (mounted) setState(() => _attachmentError = error.toString());
      rethrow;
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

  Future<ArticleMediaItem> _uploadInlineImage(PickedAppFile file) {
    setState(() => _dirty = true);
    return _uploadFile(file: file, kind: 'inline_image');
  }

  Future<void> _removeAttachment(ArticleMediaItem item) async {
    try {
      await _deleteMediaId(item.id);
      if (!mounted) return;
      setState(() {
        _attachments.removeWhere((row) => row.id == item.id);
        _dirty = true;
      });
    } catch (_) {}
  }

  Map<String, dynamic> _savePayload() {
    final article = _article!;
    final editor = _editorValue;
    var content = editor.content.trim();
    final raw = article.content ?? '';
    const marker = '----EXTRACTED METADATA----';
    final markerIndex = raw.indexOf(marker);
    if (markerIndex >= 0) {
      content = '$content\n\n${raw.substring(markerIndex)}';
    }
    final payload = article.toUpdatePayload(
      title: _titleCtrl.text.trim(),
      category: _categoryCtrl.text.trim(),
      summary: _summaryCtrl.text.trim(),
      content: content,
      office: _resolvedOffice() ?? '',
      sourceFilename: _sourceCtrl.text.trim(),
      audience: _audience,
      contentFormat: editor.contentFormat,
      mediaIds: _attachments.map((item) => item.id).toList(),
    );
    payload['source_section'] = _sourceSectionCtrl.text.trim();
    return payload;
  }

  Future<void> _saveChanges() async {
    if (_saving || _article == null) return;
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
    setState(() {
      _saving = true;
      _pendingAction = 'save';
      _error = null;
    });
    try {
      if (widget.debugUpdateArticle != null) {
        await widget.debugUpdateArticle!(widget.articleId, _savePayload());
      } else {
        await _service.updateArticle(widget.articleId, _savePayload());
      }
      if (!mounted) return;
      setState(() {
        _saved = true;
        _dirty = false;
      });
      Navigator.of(context).pop(true);
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

  Future<void> _publish() async {
    if (_saving || _article == null) return;
    if (_editorValue.isEmpty) {
      setState(() {
        _error =
            'Article content is empty. Correct it and save before publishing.';
      });
      return;
    }
    setState(() {
      _saving = true;
      _pendingAction = 'publish';
      _error = null;
    });
    try {
      if (widget.debugPublishArticle != null) {
        await widget.debugPublishArticle!(widget.articleId);
      } else {
        await _service.publishArticle(widget.articleId);
      }
      if (!mounted) return;
      setState(() {
        _published = true;
        _statusChanged = true;
        _dirty = false;
      });
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

  Future<void> _unpublish() async {
    if (_saving || _article == null) return;
    setState(() {
      _saving = true;
      _pendingAction = 'unpublish';
      _error = null;
    });
    try {
      if (widget.debugUnpublishArticle != null) {
        await widget.debugUnpublishArticle!(widget.articleId);
      } else {
        await _service.unpublishArticle(widget.articleId);
      }
      if (!mounted) return;
      setState(() {
        _published = false;
        _statusChanged = true;
      });
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
                  returnTo: (_) => KnowledgeArticleEditPage(
                    articleId: widget.articleId,
                    setAdminHeader: widget.setAdminHeader,
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
      canPop: (!_dirty || _saved) && !_saving,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;
        await _handleBack();
      },
      child: _buildBody(),
    );

    if (_isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeKnowledgeArticles,
        title: 'Edit Article',
        description: 'Update the content and details of this knowledge base article.',
        fillBody: true,
        showHeader: false,
        child: body,
      );
    }

    return AdminScaffold(
      current: StudentNavItem.adminKnowledgeArticles,
      title: 'Edit Article',
      description: 'Update the content and details of this knowledge base article.',
      fillBody: true,
      showHeader: false,
      child: body,
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const ColoredBox(
        color: DesignTokens.adminSurface,
        child: Center(
          child: CircularProgressIndicator(color: DesignTokens.maroon),
        ),
      );
    }
    if (_loadError != null || _article == null) {
      return ColoredBox(
        color: DesignTokens.adminSurface,
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SelectableText(
                    _loadError?.toString() ?? 'Article not found.',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 16),
                  TextButton.icon(
                    key: const Key('knowledge-article-edit-back'),
                    onPressed: () => Navigator.of(context).pop(false),
                    icon: const Icon(Icons.arrow_back, size: 18),
                    label: const Text('Back to Articles'),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }
    return _buildWorkspace();
  }

  Widget _buildWorkspace() {
    return ColoredBox(
      color: DesignTokens.adminSurface,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 900;
          final stacked = constraints.maxWidth < 720;
          return SingleChildScrollView(
            key: const Key('knowledge-article-edit-page'),
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
                      breadcrumbCurrent: 'Edit Article',
                      title: 'Edit Article',
                      subtitle:
                          'Update the content and details of this knowledge base article.',
                      backButtonKey: const Key('knowledge-article-edit-back'),
                    ),
                    const SizedBox(height: 18),
                    if (stacked) ...[
                      _buildArticleInformation(),
                      const SizedBox(height: 14),
                      _buildAdditionalDetails(),
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
                            child: _buildArticleInformation(),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            flex: 3,
                            child: Column(
                              children: [
                                _buildAdditionalDetails(),
                                const SizedBox(height: 14),
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

  Widget _buildArticleInformation() {
    return ArticleWorkspacePanel(
      title: 'Article Information',
      subtitle: 'Update the core details of the article.',
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
                  key: const Key('knowledge-article-edit-title'),
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
                  key: const Key('knowledge-article-edit-category'),
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
              final audience = articleLabeledField(
                label: 'Audience',
                child: DropdownButtonFormField<String>(
                  key: const Key('knowledge-article-edit-audience'),
                  value: _audience,
                  isExpanded: true,
                  decoration: articleInputDecoration(),
                  items: const [
                    DropdownMenuItem(value: 'student', child: Text('Student')),
                    DropdownMenuItem(value: 'faculty', child: Text('Faculty')),
                    DropdownMenuItem(value: 'both', child: Text('Both')),
                  ],
                  onChanged: _saving
                      ? null
                      : (next) {
                          if (next == null) return;
                          setState(() {
                            _audience = next;
                            _dirty = true;
                          });
                        },
                ),
              );
              final office = articleLabeledField(
                label: 'Office',
                required: _isOffice,
                child: _buildOfficeField(),
              );
              if (stackFields) {
                return Column(
                  children: [
                    audience,
                    const SizedBox(height: 14),
                    office,
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: audience),
                  const SizedBox(width: 14),
                  Expanded(child: office),
                ],
              );
            },
          ),
          const SizedBox(height: 14),
          articleLabeledField(
            label: 'Summary',
            helper: 'Optional short description shown in article lists.',
            child: TextFormField(
              key: const Key('knowledge-article-edit-summary'),
              controller: _summaryCtrl,
              enabled: !_saving,
              minLines: 2,
              maxLines: 4,
              decoration: articleInputDecoration(
                hint: 'Add a short summary (optional)',
              ),
            ),
          ),
          const SizedBox(height: 14),
          articleLabeledField(
            label: 'Article Content',
            required: true,
            helper:
                'Write the full content of the article. You can format text, add links, and include images.',
            child: KeyedSubtree(
              key: const Key('knowledge-article-edit-content'),
              child: ArticleRichEditor(
                key: _editorKey,
                initialContent: _article?.displayContent ?? '',
                contentFormat: _article?.contentFormat ?? 'plain',
                enabled: !_saving,
                imageHeaders: _mediaHeaders(),
                debugPickImage: widget.debugPickImage,
                onChanged: (_) => _markDirty(),
                onUploadImage: _saving ? null : _uploadInlineImage,
              ),
            ),
          ),
          if ((_article?.officialSourceExcerpt ?? '').trim().isNotEmpty) ...[
            const SizedBox(height: 14),
            OfficialSourceExcerptPanel(
              excerpt: _article!.officialSourceExcerpt!,
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildOfficeField() {
    if (_isOffice) {
      final name = _lockedOfficeName.isEmpty
          ? (_officeTextCtrl.text.trim().isEmpty
              ? 'Not assigned'
              : _officeTextCtrl.text.trim())
          : _lockedOfficeName;
      return InputDecorator(
        key: const Key('knowledge-article-edit-office'),
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
      final value =
          _selectedOffice != null && _offices.contains(_selectedOffice)
              ? _selectedOffice
              : null;
      return DropdownButtonFormField<String>(
        key: const Key('knowledge-article-edit-office'),
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
      key: const Key('knowledge-article-edit-office'),
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

  Widget _buildAdditionalDetails() {
    return ArticleWorkspacePanel(
      title: 'Additional Details',
      subtitle: 'Manage references and article metadata.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          articleLabeledField(
            label: 'Source filename',
            child: TextFormField(
              key: const Key('knowledge-article-edit-source'),
              controller: _sourceCtrl,
              enabled: !_saving,
              decoration: articleInputDecoration(
                hint: 'Link to a source file or reference (optional)',
              ),
            ),
          ),
          const SizedBox(height: 14),
          articleLabeledField(
            label: 'Source section',
            child: TextFormField(
              key: const Key('knowledge-article-edit-source-section'),
              controller: _sourceSectionCtrl,
              enabled: !_saving,
              decoration: articleInputDecoration(
                hint: 'Optional source section',
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPublishSettings() {
    final updated = formatArticleTimestamp(
      _article?.updatedAt ?? _article?.publishedAt ?? _article?.createdAt,
    );
    return ArticleWorkspacePanel(
      title: 'Publish Settings',
      subtitle: 'Control the status and visibility of this article.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          articleLabeledField(
            label: 'Status',
            child: InputDecorator(
              key: const Key('knowledge-article-edit-status'),
              decoration: articleInputDecoration(),
              child: Text(
                _published ? 'Published' : 'Draft',
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
          articleLabeledField(
            label: 'Last updated',
            child: InputDecorator(
              key: const Key('knowledge-article-edit-updated'),
              decoration: articleInputDecoration(),
              child: Row(
                children: [
                  const Icon(
                    Icons.calendar_today_outlined,
                    size: 16,
                    color: DesignTokens.muted,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      updated.isEmpty ? '—' : updated,
                      style: const TextStyle(
                        color: DesignTokens.ink,
                        fontWeight: FontWeight.w700,
                        fontSize: 14,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAttachments() {
    return ArticleWorkspacePanel(
      title: 'Attachments (optional)',
      subtitle:
          'Upload images, PDFs, or other supported documents to support this article.',
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

  Widget _buildActions() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (_error != null) ...[
          Container(
            key: const Key('knowledge-article-edit-error'),
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
            final secondary = _published
                ? OutlinedButton.icon(
                    key: const Key('knowledge-article-edit-unpublish'),
                    onPressed: _saving ? null : _unpublish,
                    icon: _pendingAction == 'unpublish'
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: DesignTokens.maroon,
                            ),
                          )
                        : const Icon(Icons.unpublished_outlined, size: 18),
                    label: const Text(
                      'Unpublish',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: DesignTokens.maroon,
                      side: const BorderSide(color: DesignTokens.maroon),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  )
                : OutlinedButton(
                    key: const Key('knowledge-article-edit-publish'),
                    onPressed: _saving ? null : _publish,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: DesignTokens.maroon,
                      side: const BorderSide(color: DesignTokens.maroon),
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
                              color: DesignTokens.maroon,
                            ),
                          )
                        : const Text(
                            'Publish',
                            style: TextStyle(fontWeight: FontWeight.w800),
                          ),
                  );
            final save = ElevatedButton(
              key: const Key('knowledge-article-edit-save'),
              onPressed: _saving ? null : _saveChanges,
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              child: _pendingAction == 'save'
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Text(
                      'Save Changes',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
            );
            if (stack) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  secondary,
                  const SizedBox(height: 10),
                  save,
                ],
              );
            }
            return Row(
              children: [
                Expanded(child: secondary),
                const SizedBox(width: 10),
                Expanded(child: save),
              ],
            );
          },
        ),
      ],
    );
  }
}
