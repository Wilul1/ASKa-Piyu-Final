import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../screens/login_page.dart';
import '../screens/student_home.dart';
import 'admin_kb_review_publish_section.dart';
import 'admin_kb_workspace.dart';
import 'office_scaffold.dart';
import '../services/admin_article_service.dart';
import '../services/api_client.dart';
import '../services/file_pick.dart';
import '../services/kb_workspace_session.dart';
import '../widgets/sidebar.dart';

class _PipelineStage {
  final String label;
  final String status;
  final String? detail;

  const _PipelineStage(
      {required this.label, required this.status, this.detail});
}

class AdminPanelPage extends StatefulWidget {
  const AdminPanelPage({
    super.key,
    this.initialTab = 0,
    this.focusArticleId,
  });

  /// 0 = Documents (extract/index), 1 = Articles (generate/publish).
  final int initialTab;
  final String? focusArticleId;

  @override
  State<AdminPanelPage> createState() => _AdminPanelPageState();
}

class _AdminPanelPageState extends State<AdminPanelPage> {
  static const String _adminKeyHeader = 'x-admin-key';

  final TextEditingController _adminKeyController = TextEditingController();
  final TextEditingController _reviewController = TextEditingController();
  final TextEditingController _retrievalController = TextEditingController();
  List<Map<String, dynamic>> _retrievalResults = [];
  bool _isRetrieving = false;
  bool _useLegacyAdminKey = false;
  int _articleLibraryRefreshToken = 0;
  int? _publishedArticleCount;
  int? _draftArticleCount;
  KbWorkspaceSession? _session;
  bool _sessionListenerAttached = false;
  final ScrollController _scrollController = ScrollController();
  final GlobalKey _articlesSectionKey = GlobalKey();
  int _scrollToArticlesAttempts = 0;

  @override
  void initState() {
    super.initState();
    _adminKeyController.text = AppConfig.savedAdminKey ?? '';
    _loadLibraryCounts();
    _loadKbStatistics();
    if (widget.initialTab == 1) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToArticles());
    }
  }

  void _scrollToArticles() {
    if (_scrollToArticlesAttempts > 8) return;
    _scrollToArticlesAttempts += 1;
    final target = _articlesSectionKey.currentContext;
    if (target == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToArticles());
      return;
    }
    Scrollable.ensureVisible(
      target,
      duration: const Duration(milliseconds: 350),
      curve: Curves.easeInOut,
      alignment: 0.05,
    );
  }

  @override
  void dispose() {
    _scrollController.dispose();
    if (_sessionListenerAttached) {
      _session?.removeListener(_onSessionChanged);
    }
    _adminKeyController.dispose();
    _reviewController.dispose();
    _retrievalController.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final session = KbWorkspaceScope.of(context);
    if (!identical(_session, session)) {
      _session?.removeListener(_onSessionChanged);
      _session = session;
      _session!.addListener(_onSessionChanged);
      _sessionListenerAttached = true;
      _bootstrapSession(session);
    }
  }

  void _bootstrapSession(KbWorkspaceSession session) {
    if (!session.isBusy &&
        session.extractionPreview == null &&
        session.reviewText.trim().isEmpty) {
      final cached = AppConfig.lastExtractionPreview;
      if (cached != null) {
        session.hydrateFromCachedPreview(cached);
      }
    }
    _syncReviewController(session);
    if (session.isBusy) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || !session.isBusy) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              session.isExtracting
                  ? 'Extraction is still running in the background.'
                  : 'Indexing is still running in the background.',
            ),
            duration: const Duration(seconds: 3),
          ),
        );
      });
    }
  }

  void _onSessionChanged() {
    final session = _session;
    if (session == null || !mounted) return;
    _syncReviewController(session);
    setState(() {});
  }

  void _syncReviewController(KbWorkspaceSession session) {
    if (_reviewController.text == session.reviewText) return;
    _reviewController.value = TextEditingValue(
      text: session.reviewText,
      selection: TextSelection.collapsed(offset: session.reviewText.length),
    );
  }

  Future<void> _loadLibraryCounts() async {
    try {
      final articles = await _articleService().listArticles();
      if (!mounted) return;
      setState(() {
        _publishedArticleCount =
            articles.where((article) => article.published).length;
        _draftArticleCount =
            articles.where((article) => !article.published).length;
      });
    } catch (_) {
      // Counts are informational; keep the workspace usable if the library call fails.
    }
  }

  Future<void> _loadKbStatistics() async {
    try {
      final headers = <String, String>{};
      _setAdminHeader(headers);
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/admin/kb/statistics',
        headers: headers,
      );
      if (result.statusCode != 200 || !mounted) return;
      final decoded = result.json;
      if (decoded is Map) {
        final session = KbWorkspaceScope.of(context);
        session.setKbStatistics(Map<String, dynamic>.from(decoded));
      }
    } catch (_) {
      // Statistics are optional for the workspace header cards.
    }
  }

  AdminArticleService _articleService() {
    return AdminArticleService(
      apiBase: AppConfig.resolvedApiBase,
      setAdminHeader: _setAdminHeader,
    );
  }

  void _refreshArticleLibrary() {
    setState(() => _articleLibraryRefreshToken++);
  }


  Future<void> _pickFile() async {
    final session = KbWorkspaceScope.of(context);
    if (session.isBusy) {
      setState(() {});
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Wait for the current extract/index job to finish before choosing another file.',
          ),
        ),
      );
      return;
    }
    final picked = await pickAppFile(
      allowedExtensions: const [
        'pdf',
        'png',
        'jpg',
        'jpeg',
        'webp',
        'bmp',
        'tif',
        'tiff',
      ],
      dialogTitle: 'Select a document',
    );
    if (picked == null) {
      return;
    }
    session.setSelectedFile(picked);
  }

  Future<void> _extractPreview() async {
    final session = KbWorkspaceScope.of(context);
    await session.runExtract(
      setAdminHeader: _setAdminHeader,
      authError: _adminAuthError,
      requestError: _adminRequestError,
      cleanPreviewText: _cleanPreviewText,
      formatDocumentTypeLabel: formatDocumentTypeLabel,
      formatClassificationReason: formatClassificationReason,
    );
  }

  Future<void> _saveToKnowledgeBase() async {
    final session = KbWorkspaceScope.of(context);
    // Keep typed review edits (if any) on the session before ingest.
    session.setReviewText(_reviewController.text);
    await session.runIngest(
      setAdminHeader: _setAdminHeader,
      authError: _adminAuthError,
      requestError: _adminRequestError,
      onIndexed: () async {
        await _loadKbStatistics();
      },
    );
  }

  Future<void> _runRetrievalTest() async {
    final session = KbWorkspaceScope.of(context);
    final question = _retrievalController.text.trim();
    if (question.length < 3) {
      session.setStatusMessage('Enter a retrieval test question first.');
      return;
    }

    setState(() {
      _isRetrieving = true;
    });
    session.setStatusMessage('Running retrieval test...');

    try {
      final headers = <String, String>{
        'Content-Type': 'application/json',
      };
      _setAdminHeader(headers);
      final result = await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/admin/kb/retrieval-test',
        headers: headers,
        jsonBody: {'question': question, 'top_k': 5},
      );

      final decoded = result.json;
      final data = decoded is Map<String, dynamic>
          ? decoded
          : <String, dynamic>{'response': decoded};

      if (result.statusCode == 200) {
        setState(() {
          _retrievalResults = _readMapList(data['results']);
        });
        final stats = _readMap(data['kb_statistics']);
        if (stats != null) {
          session.setKbStatistics(stats);
        }
        session.setStatusMessage(
          'Retrieval test returned ${_retrievalResults.length} chunks.',
        );
      } else {
        session.setStatusMessage(
          _adminRequestError(result.statusCode, data['detail']),
        );
      }
    } on StateError catch (error) {
      session.setStatusMessage(_adminAuthError(error.message));
    } catch (error) {
      session.setStatusMessage('Could not reach the backend.');
    } finally {
      if (mounted) {
        setState(() => _isRetrieving = false);
      }
    }
  }

  // Extract/ingest run on [KbWorkspaceSession] so they survive page disposal.

  void _setAdminHeader(Map<String, String> headers) {
    final auth = AuthScope.of(context);
    final token = auth.accessToken;
    // Release builds never accept the shared X-Admin-Key path.
    if (!_useLegacyAdminKey || kReleaseMode) {
      final role = auth.role;
      if (role != 'admin' && role != 'office') {
        throw StateError('not_admin');
      }
      if (token == null || token.trim().isEmpty) {
        throw StateError('missing_admin_token');
      }
      headers['Authorization'] = 'Bearer $token';
      return;
    }

    final key = _adminKeyController.text.trim();
    if (key.isEmpty) {
      throw StateError('missing_legacy_admin_key');
    }
    AppConfig.savedAdminKey = key;
    headers[_adminKeyHeader] = key;
  }

  String _adminAuthError(String message) {
    if (message == 'not_admin') {
      return 'Only admin or office accounts can use Knowledge Base tools.';
    }
    if (message == 'missing_admin_token') {
      return 'Authorization failed. Please log in again.';
    }
    if (message == 'missing_legacy_admin_key') {
      return 'Authorization failed. Please log in again as admin.';
    }
    return 'Authorization failed. Please log in again.';
  }

  String _adminRequestError(int? status, dynamic detail) {
    if (status == 0) {
      return 'Could not reach the backend.';
    }
    if (status == 403) {
      return 'Only admin or office accounts can use Knowledge Base tools.';
    }
    if (status == 401) {
      return 'Authorization failed. Please log in again.';
    }
    final text = detail?.toString().trim() ?? '';
    if (text.isNotEmpty) {
      return text;
    }
    return status == null
        ? 'Request failed.'
        : 'Request failed with status $status.';
  }

  String _cleanPreviewText(String value) {
    final marker = RegExp(r'^\s*Raw Extraction:\s*$',
        multiLine: true, caseSensitive: false);
    final match = marker.firstMatch(value);
    if (match == null) {
      return value.trim();
    }
    return value.substring(0, match.start).trimRight();
  }

  Map<String, dynamic>? _readMap(dynamic value) {
    if (value is Map) {
      return Map<String, dynamic>.from(value);
    }
    return null;
  }

  List<Map<String, dynamic>> _readMapList(dynamic value) {
    if (value is! List) {
      return [];
    }
    return value
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  List<Widget> _buildExtractTab() {
    final session = KbWorkspaceScope.of(context);
    return [
      if (session.isBusy) ...[
        Container(
          width: double.infinity,
          margin: const EdgeInsets.only(bottom: 12),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            color: const Color(0xFFFFF8E8),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: const Color(0xFFE6C87A)),
          ),
          child: Row(
            children: [
              const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  session.isExtracting
                      ? 'Extraction is running. You can open other pages and return here — progress will still be here.'
                      : 'Indexing is running. You can open other pages and return here — progress will still be here.',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: DesignTokens.maroon,
                    height: 1.35,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
      AdminKbWorkspace(
        fileName: session.selectedFileName,
        fileSizeBytes: session.selectedFile?.bytes.length,
        isBusy: session.isBusy,
        status: session.status,
        pipelineStages: session.pipelineStages
            .map(
              (stage) => AdminPipelineStageView(
                label: stage.label,
                status: stage.status,
                detail: stage.detail,
              ),
            )
            .toList(),
        knowledgeUnits: session.knowledgeUnits,
        validationReport: session.validationReport,
        kbStatistics: session.kbStatistics,
        reviewText: session.reviewText,
        rawOcrText: session.rawOcrText,
        documentType: session.extractedDocumentType,
        classificationReason: session.classificationReason,
        publishedCount: _publishedArticleCount,
        draftCount: _draftArticleCount,
        candidateHintCount: session.candidateHintCount,
        selectedOutlineIndex: session.selectedOutlineIndex,
        onPickFile: _pickFile,
        onExtract: _extractPreview,
        onIngest: _saveToKnowledgeBase,
        onSelectOutline: (index) {
          session.setSelectedOutlineIndex(index);
        },
      ),
    ];
  }

  Widget _buildUnifiedBody() {
    final session = KbWorkspaceScope.of(context);
    return ListView(
      controller: _scrollController,
      padding: const EdgeInsets.fromLTRB(4, 12, 4, 24),
      children: [
        ..._buildExtractTab(),
        const SizedBox(height: 20),
        KeyedSubtree(
          key: _articlesSectionKey,
          child: KbReviewAndPublishSection(
            knowledgeUnits: session.knowledgeUnits,
            fileName: session.selectedFileName,
            documentType: session.extractedDocumentType,
            focusArticleId: widget.focusArticleId,
            onLibraryRefresh: () {
              setState(() => _articleLibraryRefreshToken++);
            },
          ),
        ),
        const SizedBox(height: 18),
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
      return _AdminLoginRequired();
    }
    if (auth.role != 'admin' && auth.role != 'office') {
      return const _AdminAccessDenied();
    }

    final isOffice = auth.role == 'office';
    final navCurrent = isOffice
        ? StudentNavItem.officeKnowledgeBase
        : StudentNavItem.adminKnowledgeBase;

    final scrollBody = _buildUnifiedBody();

    if (isOffice) {
      return OfficeScaffold(
        current: StudentNavItem.officeKnowledgeBase,
        title: 'Knowledge Base',
        description:
            'Extract campus documents for Ask, then generate and publish public articles.',
        fillBody: true,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
          child: scrollBody,
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final body = ColoredBox(
          color: DesignTokens.adminSurface,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(24, 18, 24, 16),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1180),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const _AdminHeader(),
                    const SizedBox(height: 16),
                    Expanded(child: scrollBody),
                  ],
                ),
              ),
            ),
          ),
        );

        if (isWide) {
          return Scaffold(
            backgroundColor: DesignTokens.adminSurface,
            body: Row(
              children: [
                SizedBox(
                  width: DesignTokens.adminSidebarWidth,
                  child: AppSidebar(current: navCurrent),
                ),
                Expanded(child: body),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.adminSurface,
          drawer: Drawer(
            backgroundColor: DesignTokens.adminSidebarBg,
            child: AppSidebar(current: navCurrent),
          ),
          appBar: AppBar(
            title: const Text('Knowledge Base'),
            backgroundColor: Colors.white,
            foregroundColor: DesignTokens.ink,
            elevation: 0.5,
          ),
          body: body,
        );
      },
    );
  }
}

class _AdminLoginRequired extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final body = Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: _AdminGuardPanel(
                title: 'Admin login required',
                message:
                    'Please log in with an admin account to use the admin panel.',
                icon: Icons.admin_panel_settings_rounded,
                action: ElevatedButton(
                  onPressed: () => Navigator.of(context).pushReplacement(
                    MaterialPageRoute(
                      builder: (_) => LoginPage(
                        returnTo: (_) => const AdminPanelPage(),
                        message:
                            'Please log in with an admin account to use the admin panel.',
                      ),
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: DesignTokens.maroon,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(vertical: 15),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                  child: const Text('Login'),
                ),
              ),
            ),
          ),
        );

        if (isWide) {
          return Scaffold(
            backgroundColor: DesignTokens.adminSurface,
            body: Row(
              children: [
                const SizedBox(
                  width: DesignTokens.adminSidebarWidth,
                  child: AppSidebar(current: StudentNavItem.adminKnowledgeBase),
                ),
                Expanded(child: body),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.adminSurface,
          drawer: const Drawer(
            backgroundColor: DesignTokens.adminSidebarBg,
            child: AppSidebar(current: StudentNavItem.adminKnowledgeBase),
          ),
          appBar: AppBar(title: const Text('Knowledge Base Admin')),
          body: body,
        );
      },
    );
  }
}

class _AdminAccessDenied extends StatelessWidget {
  const _AdminAccessDenied();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DesignTokens.bgGrey,
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: _AdminGuardPanel(
              title: 'Admin access only',
              message:
                  'Only admin accounts can use Knowledge Base Admin tools.',
              icon: Icons.lock_outline_rounded,
              action: OutlinedButton(
                onPressed: () => Navigator.of(context).pushAndRemoveUntil(
                  MaterialPageRoute(builder: (_) => const StudentHomePage()),
                  (route) => false,
                ),
                style: OutlinedButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                  side: const BorderSide(color: DesignTokens.maroon),
                  padding: const EdgeInsets.symmetric(vertical: 15),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
                child: const Text('Return Home'),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _AdminGuardPanel extends StatelessWidget {
  final String title;
  final String message;
  final IconData icon;
  final Widget action;

  const _AdminGuardPanel({
    required this.title,
    required this.message,
    required this.icon,
    required this.action,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Icon(icon, color: DesignTokens.maroon, size: 42),
          const SizedBox(height: 16),
          Text(
            title,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w900,
              fontSize: 24,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            message,
            style: const TextStyle(color: DesignTokens.muted, height: 1.45),
          ),
          const SizedBox(height: 22),
          action,
        ],
      ),
    );
  }
}

class _AdminHeader extends StatelessWidget {
  const _AdminHeader();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: DesignTokens.primaryBlue.withOpacity(0.10),
            borderRadius: BorderRadius.circular(8),
          ),
          child: const Icon(Icons.admin_panel_settings_rounded,
              color: DesignTokens.primaryBlue),
        ),
        const SizedBox(width: 14),
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Knowledge Base',
                style: TextStyle(
                    fontSize: 30,
                    fontWeight: FontWeight.w800,
                    color: Color(0xFF203B63)),
              ),
              SizedBox(height: 6),
              Text(
                'Extract documents for Ask, then generate and publish public articles.',
                style: TextStyle(
                    fontSize: 14, height: 1.45, color: Color(0xFF6C7785)),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _AdminAdvancedOptionsPanel extends StatelessWidget {
  final TextEditingController controller;
  final bool useLegacyAdminKey;
  final ValueChanged<bool> onToggleLegacy;
  final TextEditingController retrievalController;
  final bool isRetrieving;
  final List<Map<String, dynamic>> retrievalResults;
  final VoidCallback onRunRetrievalTest;

  const _AdminAdvancedOptionsPanel({
    required this.controller,
    required this.useLegacyAdminKey,
    required this.onToggleLegacy,
    required this.retrievalController,
    required this.isRetrieving,
    required this.retrievalResults,
    required this.onRunRetrievalTest,
  });

  @override
  Widget build(BuildContext context) {
    return _Panel(
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: const EdgeInsets.only(top: 8),
          title: const Text(
            'Advanced developer options',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: DesignTokens.muted,
            ),
          ),
          subtitle: const Text(
            'Bearer token is used automatically when logged in as admin.',
            style: TextStyle(fontSize: 12, color: DesignTokens.muted),
          ),
          children: [
            if (!kReleaseMode) ...[
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Use legacy API key'),
                subtitle: const Text(
                  'For scripts and local development without admin login.',
                ),
                value: useLegacyAdminKey,
                onChanged: onToggleLegacy,
              ),
              if (useLegacyAdminKey) ...[
                const SizedBox(height: 8),
                TextField(
                  controller: controller,
                  obscureText: true,
                  onChanged: (value) => AppConfig.savedAdminKey = value,
                  decoration: InputDecoration(
                    labelText: 'Admin API key',
                    hintText: 'Enter the backend admin key for this session',
                    prefixIcon: const Icon(Icons.key_rounded),
                    filled: true,
                    fillColor: const Color(0xFFF8FAFC),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                      borderSide: const BorderSide(color: DesignTokens.border),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                      borderSide: const BorderSide(color: DesignTokens.border),
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 12),
              const Divider(),
              const SizedBox(height: 8),
            ],
            _RetrievalTestPanel(
              controller: retrievalController,
              isBusy: isRetrieving,
              results: retrievalResults,
              onRun: onRunRetrievalTest,
            ),
          ],
        ),
      ),
    );
  }
}

class _UploadPanel extends StatelessWidget {
  final String? fileName;
  final bool isBusy;
  final VoidCallback onPickFile;
  final VoidCallback onExtract;
  final VoidCallback onIngest;

  const _UploadPanel({
    required this.fileName,
    required this.isBusy,
    required this.onPickFile,
    required this.onExtract,
    required this.onIngest,
  });

  @override
  Widget build(BuildContext context) {
    return _Panel(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 720;
          final picker = InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: isBusy ? null : onPickFile,
            child: Container(
              height: 64,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                border: Border.all(color: const Color(0xFFDEE5EE)),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  const Icon(Icons.upload_file_rounded,
                      color: DesignTokens.primaryBlue),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      fileName ?? 'Choose PDF or image',
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w700,
                          color: Color(0xFF203B63)),
                    ),
                  ),
                ],
              ),
            ),
          );

          final actions = Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _ActionButton(
                icon: Icons.auto_fix_high_rounded,
                label: 'Extract & Structure',
                onPressed: isBusy ? null : onExtract,
                filled: true,
              ),
              _ActionButton(
                icon: Icons.cloud_upload_rounded,
                label: 'Index for Chatbot Retrieval',
                onPressed: isBusy ? null : onIngest,
                filled: false,
              ),
            ],
          );

          const indexHelper = Text(
            'This indexes extracted knowledge units into ChromaDB for Ask ASKa-Piyu retrieval and citation grounding. It does not publish articles to the public Knowledge Base.',
            style: TextStyle(
              fontSize: 12,
              height: 1.4,
              color: DesignTokens.muted,
            ),
          );

          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                picker,
                const SizedBox(height: 12),
                actions,
                const SizedBox(height: 10),
                indexHelper,
              ],
            );
          }

          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(child: picker),
                  const SizedBox(width: 12),
                  actions,
                ],
              ),
              const SizedBox(height: 10),
              indexHelper,
            ],
          );
        },
      ),
    );
  }
}


class _SummaryChip extends StatelessWidget {
  const _SummaryChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: DesignTokens.maroon.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Text(
        '$label: $value',
        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
      ),
    );
  }
}

class _GenerationMetric extends StatelessWidget {
  const _GenerationMetric(this.label, this.value);

  final String label;
  final int value;

  @override
  Widget build(BuildContext context) {
    return Text('$label: $value', style: const TextStyle(fontSize: 13));
  }
}

class _ResultPanel extends StatelessWidget {
  final String status;
  final TextEditingController controller;
  final List<_PipelineStage> stages;
  final bool isBusy;
  final String? rawOcrText;

  const _ResultPanel({
    required this.status,
    required this.controller,
    required this.stages,
    required this.isBusy,
    required this.rawOcrText,
  });

  @override
  Widget build(BuildContext context) {
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isBusy ? Icons.hourglass_top_rounded : Icons.fact_check_rounded,
                color: DesignTokens.primaryBlue,
                size: 20,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  status,
                  style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: Color(0xFF203B63)),
                ),
              ),
            ],
          ),
          if (isBusy) ...[
            const SizedBox(height: 14),
            const LinearProgressIndicator(minHeight: 3),
          ],
          const SizedBox(height: 16),
          _PipelineStageStrip(stages: stages),
          const SizedBox(height: 16),
          Container(
            width: double.infinity,
            constraints: const BoxConstraints(minHeight: 360),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF101828),
              borderRadius: BorderRadius.circular(8),
            ),
            child: TextField(
              controller: controller,
              maxLines: null,
              minLines: 16,
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 13,
                height: 1.5,
                color: Color(0xFFEAF0F6),
              ),
              decoration: const InputDecoration(
                border: InputBorder.none,
                hintText: 'Review text will appear here before indexing.',
                hintStyle: TextStyle(color: Color(0xFF8A96A8)),
              ),
            ),
          ),
          _RawOcrDebugPanel(rawOcrText: rawOcrText),
        ],
      ),
    );
  }
}

class _RawOcrDebugPanel extends StatelessWidget {
  final String? rawOcrText;

  const _RawOcrDebugPanel({required this.rawOcrText});

  @override
  Widget build(BuildContext context) {
    final text = rawOcrText?.trim();
    if (text == null || text.isEmpty) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xFFF8FAFC),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: DesignTokens.border),
        ),
        child: ExpansionTile(
          initiallyExpanded: false,
          tilePadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
          childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
          leading: const Icon(Icons.bug_report_rounded,
              color: DesignTokens.primaryBlue),
          title: const Text(
            'View Raw OCR Text',
            style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w800,
                color: Color(0xFF203B63)),
          ),
          subtitle: const Text(
            'Raw OCR text is only used for admin verification and is not shown to students.',
            style: TextStyle(fontSize: 12, color: DesignTokens.muted),
          ),
          children: [
            Container(
              width: double.infinity,
              constraints: const BoxConstraints(maxHeight: 320),
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: DesignTokens.border),
              ),
              child: SingleChildScrollView(
                child: SelectableText(
                  text,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12,
                    height: 1.45,
                    color: Color(0xFF1F2937),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ValidationPanel extends StatelessWidget {
  final Map<String, dynamic>? report;

  const _ValidationPanel({required this.report});

  @override
  Widget build(BuildContext context) {
    final data = report;
    if (data == null) {
      return const SizedBox.shrink();
    }
    final status = (data['status'] ?? 'Needs Review').toString();
    final ready = status == 'Ready for Indexing';
    final metrics = [
      ['Document type', data['document_type']],
      ['Knowledge units', data['total_knowledge_units']],
      ['Chunks', data['total_chunks']],
      ['Average chunk words', data['average_chunk_words']],
      ['Largest chunk words', data['largest_chunk_words']],
      ['Smallest chunk words', data['smallest_chunk_words']],
      ['Missing metadata', data['missing_metadata_count']],
      ['TOC-like units', data['toc_like_units_count']],
      ['Empty units', data['empty_units_count']],
      ['Suspicious units', data['suspicious_units_count']],
      ['Oversized chunks', data['oversized_chunks_count']],
    ];

    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SectionHeader(
            icon: Icons.verified_rounded,
            title: 'Validation Report',
            trailing: _StatusChip(
              label: status,
              color: ready ? const Color(0xFF2C9C5B) : const Color(0xFFD97706),
            ),
          ),
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final width = constraints.maxWidth >= 860
                  ? (constraints.maxWidth - 30) / 3
                  : constraints.maxWidth >= 560
                      ? (constraints.maxWidth - 15) / 2
                      : constraints.maxWidth;
              return Wrap(
                spacing: 15,
                runSpacing: 12,
                children: metrics.map((metric) {
                  return SizedBox(
                    width: width,
                    child: _MetricTile(
                        label: metric[0].toString(),
                        value: '${metric[1] ?? 0}'),
                  );
                }).toList(),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _KnowledgeUnitsPanel extends StatefulWidget {
  final List<Map<String, dynamic>> units;

  const _KnowledgeUnitsPanel({required this.units});

  @override
  State<_KnowledgeUnitsPanel> createState() => _KnowledgeUnitsPanelState();
}

class _KnowledgeUnitsPanelState extends State<_KnowledgeUnitsPanel> {
  static const int _pageSize = 20;
  int _visibleCount = _pageSize;
  String _filter = 'All';
  bool _expanded = false;

  @override
  void didUpdateWidget(covariant _KnowledgeUnitsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.units, widget.units)) {
      _visibleCount = _pageSize;
      _filter = 'All';
    }
  }

  List<Map<String, dynamic>> get _filteredUnits {
    return widget.units.where((unit) {
      final status = (unit['status'] ?? 'OK').toString();
      final reasons = unit['suspicious_reasons'];
      final reasonText = reasons is List ? reasons.join(' ').toLowerCase() : '';
      if (_filter == 'OK') {
        return status == 'OK';
      }
      if (_filter == 'Suspicious') {
        return status == 'Suspicious';
      }
      if (_filter == 'TOC-like') {
        return reasonText.contains('toc_like') || reasonText.contains('toc');
      }
      return true;
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.units.isEmpty) {
      return const SizedBox.shrink();
    }
    final filtered = _filteredUnits;
    final visible = filtered.take(_visibleCount).toList();
    return _Panel(
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: const EdgeInsets.only(top: 12),
          initiallyExpanded: false,
          onExpansionChanged: (value) => setState(() => _expanded = value),
          title: Row(
            children: [
              const Expanded(
                child: _SectionHeader(
                  icon: Icons.article_rounded,
                  title: 'Knowledge Units',
                ),
              ),
              _StatusChip(
                label: '${filtered.length} units',
                color: DesignTokens.primaryBlue,
              ),
            ],
          ),
          subtitle: const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Text(
              'Knowledge Units are extracted sections used for RAG retrieval and citation grounding. They are not public Knowledge Base articles.',
              style: TextStyle(fontSize: 12, color: DesignTokens.muted, height: 1.4),
            ),
          ),
          children: [
            if (_expanded) ...[
              _FilterBar(
                selected: _filter,
                counts: {
                  'All': widget.units.length,
                  'OK': widget.units
                      .where((unit) => (unit['status'] ?? 'OK').toString() == 'OK')
                      .length,
                  'Suspicious': widget.units
                      .where((unit) =>
                          (unit['status'] ?? 'OK').toString() == 'Suspicious')
                      .length,
                  'TOC-like': widget.units.where((unit) {
                    final reasons = unit['suspicious_reasons'];
                    final reasonText =
                        reasons is List ? reasons.join(' ').toLowerCase() : '';
                    return reasonText.contains('toc_like') ||
                        reasonText.contains('toc');
                  }).length,
                },
                onSelected: (value) {
                  setState(() {
                    _filter = value;
                    _visibleCount = _pageSize;
                  });
                },
              ),
              const SizedBox(height: 12),
              if (visible.isEmpty)
                const _EmptyListMessage(
                    message: 'No units match the selected filter.')
              else
                ListView.builder(
                  key: ValueKey('knowledge-units-$_filter-${visible.length}'),
                  itemCount: visible.length,
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  itemBuilder: (context, index) =>
                      _KnowledgeUnitRow(unit: visible[index]),
                ),
              if (filtered.length > visible.length) ...[
                const SizedBox(height: 8),
                _LoadMoreButton(
                  remaining: filtered.length - visible.length,
                  onPressed: () {
                    setState(() {
                      _visibleCount += _pageSize;
                      if (_visibleCount > filtered.length) {
                        _visibleCount = filtered.length;
                      }
                    });
                  },
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

class _KnowledgeUnitRow extends StatelessWidget {
  final Map<String, dynamic> unit;

  const _KnowledgeUnitRow({required this.unit});

  @override
  Widget build(BuildContext context) {
    final status = (unit['status'] ?? 'OK').toString();
    final suspicious = status == 'Suspicious';
    final title = (unit['title'] ?? 'Untitled').toString();
    final path = _truncatePath((unit['hierarchy_path'] ?? '').toString());
    final pages = _pageRange(unit);

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
            color:
                suspicious ? const Color(0xFFF3B26B) : const Color(0xFFDEE5EE)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF203B63)),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    _MiniMeta(
                        label: 'Type',
                        value: (unit['content_type'] ?? 'policy').toString()),
                    _MiniMeta(
                        label: 'Words', value: '${unit['word_count'] ?? 0}'),
                    if (pages.isNotEmpty)
                      _MiniMeta(label: 'Pages', value: pages),
                    if (path.isNotEmpty) _MiniMeta(label: 'Path', value: path),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              _StatusChip(
                label: status,
                color: suspicious
                    ? const Color(0xFFD97706)
                    : const Color(0xFF2C9C5B),
              ),
              const SizedBox(height: 8),
              TextButton.icon(
                onPressed: () => _showUnit(context, unit),
                icon: const Icon(Icons.visibility_rounded, size: 16),
                label: const Text('View'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static void _showUnit(BuildContext context, Map<String, dynamic> unit) {
    showDialog<void>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: Text((unit['title'] ?? 'Knowledge Unit').toString()),
          content: SizedBox(
            width: 720,
            child: SingleChildScrollView(
              child: SelectableText(
                (unit['content'] ?? '').toString(),
                style: const TextStyle(fontSize: 13, height: 1.45),
              ),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Close')),
          ],
        );
      },
    );
  }
}

class _ChunkPreviewPanel extends StatefulWidget {
  final List<Map<String, dynamic>> chunks;

  const _ChunkPreviewPanel({required this.chunks});

  @override
  State<_ChunkPreviewPanel> createState() => _ChunkPreviewPanelState();
}

class _ChunkPreviewPanelState extends State<_ChunkPreviewPanel> {
  static const int _pageSize = 20;
  int _visibleCount = _pageSize;

  @override
  void didUpdateWidget(covariant _ChunkPreviewPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.chunks, widget.chunks)) {
      _visibleCount = _pageSize;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.chunks.isEmpty) {
      return const SizedBox.shrink();
    }
    final visible = widget.chunks.take(_visibleCount).toList();
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _SectionHeader(
            icon: Icons.hub_rounded,
            title: 'Chunk Preview',
            trailing: _StatusChip(
              label: '${visible.length}/${widget.chunks.length} shown',
              color: DesignTokens.primaryBlue,
            ),
          ),
          const SizedBox(height: 12),
          ListView.builder(
            key: ValueKey('chunk-preview-${visible.length}'),
            itemCount: visible.length,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemBuilder: (context, index) =>
                _ChunkPreviewRow(chunk: visible[index]),
          ),
          if (widget.chunks.length > visible.length) ...[
            const SizedBox(height: 8),
            _LoadMoreButton(
              remaining: widget.chunks.length - visible.length,
              onPressed: () {
                setState(() {
                  _visibleCount += _pageSize;
                  if (_visibleCount > widget.chunks.length) {
                    _visibleCount = widget.chunks.length;
                  }
                });
              },
            ),
          ],
        ],
      ),
    );
  }
}

class _ChunkPreviewRow extends StatelessWidget {
  final Map<String, dynamic> chunk;

  const _ChunkPreviewRow({required this.chunk});

  @override
  Widget build(BuildContext context) {
    final path = _truncatePath((chunk['hierarchy_path'] ?? '').toString());
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFDEE5EE)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    _MiniMeta(
                        label: 'Chunk', value: '${chunk['chunk_index'] ?? 0}'),
                    _MiniMeta(
                        label: 'Title',
                        value: (chunk['title'] ?? 'Untitled').toString()),
                    _MiniMeta(
                        label: 'Words', value: '${chunk['word_count'] ?? 0}'),
                    if (path.isNotEmpty) _MiniMeta(label: 'Path', value: path),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              TextButton.icon(
                onPressed: () => _showChunk(context, chunk),
                icon: const Icon(Icons.visibility_rounded, size: 16),
                label: const Text('View'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            (chunk['content_preview'] ?? '').toString(),
            style: const TextStyle(
                fontSize: 13, height: 1.45, color: Color(0xFF334155)),
          ),
        ],
      ),
    );
  }

  static void _showChunk(BuildContext context, Map<String, dynamic> chunk) {
    showDialog<void>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: Text(
              'Chunk ${chunk['chunk_index'] ?? ''}: ${(chunk['title'] ?? 'Untitled').toString()}'),
          content: SizedBox(
            width: 720,
            child: SingleChildScrollView(
              child: SelectableText(
                (chunk['content'] ?? chunk['content_preview'] ?? '').toString(),
                style: const TextStyle(fontSize: 13, height: 1.45),
              ),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Close')),
          ],
        );
      },
    );
  }
}

class _RetrievalTestPanel extends StatelessWidget {
  final TextEditingController controller;
  final bool isBusy;
  final List<Map<String, dynamic>> results;
  final VoidCallback onRun;

  const _RetrievalTestPanel({
    required this.controller,
    required this.isBusy,
    required this.results,
    required this.onRun,
  });

  @override
  Widget build(BuildContext context) {
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionHeader(
              icon: Icons.manage_search_rounded, title: 'Retrieval Test'),
          const SizedBox(height: 12),
          LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 680;
              final field = TextField(
                controller: controller,
                decoration: const InputDecoration(
                  labelText: 'Test Retrieval Question',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
              );
              final button = _ActionButton(
                icon: Icons.play_arrow_rounded,
                label: isBusy ? 'Running' : 'Run Retrieval Test',
                onPressed: isBusy ? null : onRun,
                filled: true,
              );
              if (compact) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    field,
                    const SizedBox(height: 10),
                    Align(alignment: Alignment.centerLeft, child: button),
                  ],
                );
              }
              return Row(
                children: [
                  Expanded(child: field),
                  const SizedBox(width: 10),
                  button,
                ],
              );
            },
          ),
          if (results.isNotEmpty) ...[
            const SizedBox(height: 14),
            ...results
                .map((result) => _RetrievalResultRow(result: result))
                .toList(),
          ],
        ],
      ),
    );
  }
}

class _RetrievalResultRow extends StatelessWidget {
  final Map<String, dynamic> result;

  const _RetrievalResultRow({required this.result});

  @override
  Widget build(BuildContext context) {
    final path = _truncatePath((result['hierarchy_path'] ?? '').toString());
    final reasons = _readReasons(result['boost_reasons']);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFDEE5EE)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              _MiniMeta(label: 'Rank', value: '${result['rank'] ?? '-'}'),
              _MiniMeta(
                  label: 'Original',
                  value: _scoreText(
                      result['original_score'] ?? result['similarity_score'])),
              _MiniMeta(
                  label: 'Reranked',
                  value: _scoreText(result['reranked_score'])),
              _MiniMeta(
                  label: 'Title',
                  value: (result['title'] ?? 'Untitled').toString()),
              if (path.isNotEmpty) _MiniMeta(label: 'Path', value: path),
              if (_pageRange(result).isNotEmpty)
                _MiniMeta(label: 'Pages', value: _pageRange(result)),
            ],
          ),
          if (reasons.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children:
                  reasons.map((reason) => _ReasonChip(label: reason)).toList(),
            ),
          ],
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => _showFullChunk(context, result),
              icon: const Icon(Icons.article_rounded, size: 16),
              label: const Text('View full chunk'),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            (result['content_preview'] ?? '').toString(),
            style: const TextStyle(
                fontSize: 13, height: 1.45, color: Color(0xFF334155)),
          ),
        ],
      ),
    );
  }

  static String _scoreText(dynamic value) {
    if (value is num) return value.toStringAsFixed(4);
    final parsed = num.tryParse((value ?? '').toString());
    return parsed == null ? '-' : parsed.toStringAsFixed(4);
  }

  static List<String> _readReasons(dynamic value) {
    if (value is! List) return const [];
    return value
        .map((item) => item.toString())
        .where((item) => item.trim().isNotEmpty)
        .toList();
  }

  static void _showFullChunk(
      BuildContext context, Map<String, dynamic> result) {
    showDialog<void>(
      context: context,
      builder: (context) {
        final title = (result['title'] ?? 'Untitled').toString();
        final path = (result['hierarchy_path'] ?? '').toString();
        final pages = _pageRange(result);
        final meta = [
          if (path.isNotEmpty) path,
          if (pages.isNotEmpty) 'Pages $pages',
        ].join(' | ');
        return AlertDialog(
          title: Text('Rank ${result['rank'] ?? '-'}: $title'),
          content: SizedBox(
            width: 760,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (meta.isNotEmpty) ...[
                    Text(meta,
                        style: const TextStyle(
                            fontSize: 12, color: Color(0xFF64748B))),
                    const SizedBox(height: 12),
                  ],
                  SelectableText(
                    (result['content'] ?? result['content_preview'] ?? '')
                        .toString(),
                    style: const TextStyle(fontSize: 13, height: 1.45),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Close')),
          ],
        );
      },
    );
  }
}

class _ReasonChip extends StatelessWidget {
  final String label;

  const _ReasonChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xFFEFF6FF),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFBFDBFE)),
      ),
      child: Text(
        label.replaceAll('_', ' '),
        style: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            color: Color(0xFF1D4ED8)),
      ),
    );
  }
}

class _StatisticsPanel extends StatelessWidget {
  final Map<String, dynamic>? statistics;

  const _StatisticsPanel({required this.statistics});

  @override
  Widget build(BuildContext context) {
    final stats = statistics;
    if (stats == null) {
      return const SizedBox.shrink();
    }
    final last = stats['last_indexed_document'] is Map
        ? Map<String, dynamic>.from(stats['last_indexed_document'])
        : null;
    final lastTitle = last == null
        ? 'None'
        : (last['title'] ?? last['source_filename'] ?? 'Untitled').toString();
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _SectionHeader(
              icon: Icons.storage_rounded, title: 'Knowledge Base Statistics'),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              _MetricTile(
                  label: 'Documents indexed',
                  value: '${stats['documents_indexed'] ?? 0}'),
              _MetricTile(
                  label: 'Total chunks indexed',
                  value: '${stats['total_chunks_indexed'] ?? 0}'),
              _MetricTile(
                  label: 'PDF citation ready',
                  value: '${stats['citation_ready_documents'] ?? 0}'),
              _MetricTile(
                  label: 'Re-index required',
                  value: '${stats['citation_reindex_required'] ?? 0}'),
              _MetricTile(
                  label: 'Embedding model',
                  value: (stats['embedding_model'] ?? '-').toString()),
              _MetricTile(
                  label: 'Vector store',
                  value: (stats['vector_store'] ?? '-').toString()),
              _MetricTile(label: 'Last indexed document', value: lastTitle),
              _MetricTile(
                  label: 'Chunks with page_number',
                  value: '${stats['chunks_with_page_number'] ?? 0}'),
            ],
          ),
          if ((stats['sample_titles'] is List) &&
              (stats['sample_titles'] as List).isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              'Sample indexed titles: ${(stats['sample_titles'] as List).take(12).join(' · ')}',
              style: const TextStyle(fontSize: 12, color: Color(0xFF334155)),
            ),
          ],
          if (stats['document_type_counts'] is Map ||
              stats['article_type_counts'] is Map) ...[
            const SizedBox(height: 6),
            Text(
              'Document types: ${_formatCountMap(stats['document_type_counts'])} · '
              'Article types: ${_formatCountMap(stats['article_type_counts'])}',
              style: const TextStyle(fontSize: 12, color: Color(0xFF64748B)),
            ),
          ],
          if (_indexedDocuments(stats).isNotEmpty) ...[
            const SizedBox(height: 16),
            const Text(
              'Level 2 citation support',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w800,
                color: DesignTokens.ink,
              ),
            ),
            const SizedBox(height: 8),
            ..._indexedDocuments(stats).map(_buildIndexedDocumentStatus),
          ],
        ],
      ),
    );
  }

  static List<Map<String, dynamic>> _indexedDocuments(Map<String, dynamic> stats) {
    final raw = stats['indexed_documents'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  static String _formatCountMap(Object? raw) {
    if (raw is! Map || raw.isEmpty) return '-';
    return raw.entries.map((e) => '${e.key}:${e.value}').join(', ');
  }

  static Widget _buildIndexedDocumentStatus(Map<String, dynamic> doc) {
    final label = (doc['source_label'] ??
            doc['source_filename'] ??
            doc['title'] ??
            doc['document_id'] ??
            'Document')
        .toString();
    final pdfStored = doc['pdf_stored'] == true;
    final rowOk = doc['source_documents_row'] == true;
    final chunksOk = doc['chunks_with_document_id'] == true;
    final ready = doc['level2_citation_ready'] == true;
    final message = (doc['message'] ?? '').toString().trim();
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: ready ? const Color(0xFFF0FDF4) : const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: ready ? const Color(0xFF86EFAC) : const Color(0xFFFDBA74),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'PDF stored: ${pdfStored ? 'yes' : 'no'} · '
            'source_documents row: ${rowOk ? 'yes' : 'no'} · '
            'chunks with document_id: ${chunksOk ? 'yes' : 'no'} · '
            'chunks: ${doc['chunk_count'] ?? 0} · '
            'chunks with page_number: ${doc['chunks_with_page_number'] ?? 0}',
            style: const TextStyle(fontSize: 12, color: Color(0xFF475569)),
          ),
          if ((doc['sample_titles'] is List) &&
              (doc['sample_titles'] as List).isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'Sample titles: ${(doc['sample_titles'] as List).take(8).join(' · ')}',
              style: const TextStyle(fontSize: 12, color: Color(0xFF334155)),
            ),
          ],
          if (doc['document_type_counts'] is Map ||
              doc['article_type_counts'] is Map) ...[
            const SizedBox(height: 4),
            Text(
              'Types: ${_formatCountMap(doc['document_type_counts'])} · '
              'Articles: ${_formatCountMap(doc['article_type_counts'])}',
              style: const TextStyle(fontSize: 12, color: Color(0xFF64748B)),
            ),
          ],
          if (message.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              message,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: Color(0xFF9A3412),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _FilterBar extends StatelessWidget {
  final String selected;
  final Map<String, int> counts;
  final ValueChanged<String> onSelected;

  const _FilterBar({
    required this.selected,
    required this.counts,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: counts.entries.map((entry) {
        final active = selected == entry.key;
        return ChoiceChip(
          selected: active,
          label: Text('${entry.key} (${entry.value})'),
          onSelected: (_) => onSelected(entry.key),
          selectedColor: DesignTokens.primaryBlue.withOpacity(0.14),
          labelStyle: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w700,
            color: active ? DesignTokens.primaryBlue : const Color(0xFF475569),
          ),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        );
      }).toList(),
    );
  }
}

class _LoadMoreButton extends StatelessWidget {
  final int remaining;
  final VoidCallback onPressed;

  const _LoadMoreButton({required this.remaining, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: onPressed,
      icon: const Icon(Icons.expand_more_rounded, size: 18),
      label: Text('Load 20 more ($remaining remaining)'),
      style: OutlinedButton.styleFrom(
        foregroundColor: DesignTokens.primaryBlue,
        side: const BorderSide(color: DesignTokens.primaryBlue),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    );
  }
}

class _EmptyListMessage extends StatelessWidget {
  final String message;

  const _EmptyListMessage({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFDEE5EE)),
      ),
      child: Text(message,
          style: const TextStyle(fontSize: 13, color: Color(0xFF64748B))),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final IconData icon;
  final String title;
  final Widget? trailing;

  const _SectionHeader(
      {required this.icon, required this.title, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(icon, color: DesignTokens.primaryBlue, size: 20),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            title,
            style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                color: Color(0xFF203B63)),
          ),
        ),
        if (trailing != null) trailing!,
      ],
    );
  }
}

class _MetricTile extends StatelessWidget {
  final String label;
  final String value;

  const _MetricTile({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minWidth: 160, maxWidth: 260),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFDEE5EE)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(fontSize: 11, color: Color(0xFF64748B))),
          const SizedBox(height: 5),
          Text(
            value,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w800,
                color: Color(0xFF203B63)),
          ),
        ],
      ),
    );
  }
}

class _MiniMeta extends StatelessWidget {
  final String label;
  final String value;

  const _MiniMeta({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 420),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFDEE5EE)),
      ),
      child: Text(
        '$label: $value',
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            color: Color(0xFF475569)),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  final String label;
  final Color color;

  const _StatusChip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: color.withOpacity(0.10),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withOpacity(0.35)),
      ),
      child: Text(
        label,
        style:
            TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: color),
      ),
    );
  }
}

String _pageRange(Map<String, dynamic> data) {
  final start = data['page_start'];
  final end = data['page_end'];
  if (start == null && end == null) {
    return '';
  }
  if (start == end || end == null) {
    return '$start';
  }
  if (start == null) {
    return '$end';
  }
  return '$start-$end';
}

String _truncatePath(String value) {
  if (value.length <= 96) {
    return value;
  }
  final parts =
      value.split(' > ').where((part) => part.trim().isNotEmpty).toList();
  if (parts.length >= 3) {
    final compact =
        '${parts.first} > ... > ${parts[parts.length - 2]} > ${parts.last}';
    if (compact.length <= 110) {
      return compact;
    }
  }
  return '${value.substring(0, 93)}...';
}

class _PipelineStageStrip extends StatelessWidget {
  final List<_PipelineStage> stages;

  const _PipelineStageStrip({required this.stages});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final itemWidth = constraints.maxWidth >= 900
            ? (constraints.maxWidth - 32) / 5
            : constraints.maxWidth >= 620
                ? (constraints.maxWidth - 16) / 3
                : constraints.maxWidth;

        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: stages.map((stage) {
            return SizedBox(
                width: itemWidth, child: _PipelineStageTile(stage: stage));
          }).toList(),
        );
      },
    );
  }
}

class _PipelineStageTile extends StatelessWidget {
  final _PipelineStage stage;

  const _PipelineStageTile({required this.stage});

  @override
  Widget build(BuildContext context) {
    final completed = stage.status == 'completed';
    final needsReview = stage.status == 'needs_review';
    final color = completed
        ? const Color(0xFF2C9C5B)
        : needsReview
            ? const Color(0xFFD97706)
            : const Color(0xFF7A8699);
    final icon = completed
        ? Icons.check_circle_rounded
        : needsReview
            ? Icons.edit_note_rounded
            : Icons.radio_button_unchecked_rounded;

    return Container(
      height: 74,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFDEE5EE)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  stage.label,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF203B63)),
                ),
                if (stage.detail != null && stage.detail!.isNotEmpty) ...[
                  const SizedBox(height: 3),
                  Text(
                    stage.detail!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 11, color: Colors.grey.shade600),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  final Widget child;

  const _Panel({required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFE8ECF2)),
        boxShadow: [
          BoxShadow(
              color: Colors.black.withOpacity(0.03),
              blurRadius: 14,
              offset: const Offset(0, 8))
        ],
      ),
      child: child,
    );
  }
}

class _ActionButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback? onPressed;
  final bool filled;

  const _ActionButton({
    required this.icon,
    required this.label,
    required this.onPressed,
    required this.filled,
  });

  @override
  Widget build(BuildContext context) {
    final style = filled
        ? ElevatedButton.styleFrom(
            backgroundColor: DesignTokens.primaryBlue,
            foregroundColor: Colors.white,
            minimumSize: const Size(104, 48),
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          )
        : OutlinedButton.styleFrom(
            foregroundColor: DesignTokens.primaryBlue,
            minimumSize: const Size(96, 48),
            side: const BorderSide(color: DesignTokens.primaryBlue),
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          );

    final child = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 18),
        const SizedBox(width: 8),
        Text(label),
      ],
    );

    if (filled) {
      return ElevatedButton(onPressed: onPressed, style: style, child: child);
    }
    return OutlinedButton(onPressed: onPressed, style: style, child: child);
  }
}
