/// Admin Dashboard "Model Evaluation" section.
///
/// Reads the real /admin/evaluation/* endpoints only -- every number shown
/// here comes from a real API response (see services/evaluation_api.dart),
/// never a hardcoded sample score. A `debugFetch*`/`debugStartRun`
/// constructor parameter lets widget tests inject canned data instead of
/// making a real HTTP call, following this codebase's existing `debug*`
/// test-seam convention (see AdminOfficesPage).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../design_tokens.dart';
import '../models/evaluation_models.dart';
import '../services/download_file.dart';
import '../services/evaluation_api.dart' as eval_api;
import '../widgets/sidebar.dart';
import 'admin_model_evaluation_charts.dart';
import 'admin_model_evaluation_classification.dart';
import 'admin_scaffold.dart';

const List<String> _kEvalTabTitles = [
  'Overview',
  'Model Inventory',
  'Component Results',
  'Comparison',
  'Confusion Matrices',
  'Performance',
  'History',
];

const int _kHistoryPageSize = 10;

typedef FetchModels = Future<List<EvaluationModelInfo>> Function();
typedef FetchSummary = Future<EvaluationSummary> Function();
typedef FetchHistory = Future<EvaluationRunHistoryPage> Function({
  required int limit,
  required int offset,
});
typedef FetchRunDetail = Future<EvaluationRunDetail> Function(String runId);
typedef StartRun = Future<String> Function();
typedef FetchConfusionMatrix = Future<EvaluationConfusionMatrix?> Function({
  required String runId,
  required String component,
});
typedef FetchCaseResults = Future<EvaluationCaseResultsPage> Function({
  required String runId,
  required String componentId,
  required int limit,
  required int offset,
});

class AdminModelEvaluationPage extends StatefulWidget {
  const AdminModelEvaluationPage({
    super.key,
    this.debugFetchModels,
    this.debugFetchSummary,
    this.debugFetchHistory,
    this.debugFetchRunDetail,
    this.debugStartRun,
    this.debugFetchConfusionMatrix,
    this.debugFetchCaseResults,
  });

  @visibleForTesting
  final FetchModels? debugFetchModels;
  @visibleForTesting
  final FetchSummary? debugFetchSummary;
  @visibleForTesting
  final FetchHistory? debugFetchHistory;
  @visibleForTesting
  final FetchRunDetail? debugFetchRunDetail;
  @visibleForTesting
  final StartRun? debugStartRun;
  @visibleForTesting
  final FetchConfusionMatrix? debugFetchConfusionMatrix;
  @visibleForTesting
  final FetchCaseResults? debugFetchCaseResults;

  @override
  State<AdminModelEvaluationPage> createState() => _AdminModelEvaluationPageState();
}

class _AdminModelEvaluationPageState extends State<AdminModelEvaluationPage>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;

  bool _initialLoading = false;
  bool _requestedInitialLoad = false;
  String? _loadError;

  List<EvaluationModelInfo> _models = const [];
  EvaluationSummary? _summary;
  EvaluationRunHistoryPage? _history;
  int _historyOffset = 0;

  String? _selectedRunId;
  EvaluationRunDetail? _selectedRunDetail;
  bool _loadingRunDetail = false;
  String? _runDetailError;
  final Map<String, EvaluationConfusionMatrix> _matrixByComponent = {};

  bool _startingRun = false;
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: _kEvalTabTitles.length, vsync: this);
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _tabController.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedInitialLoad) return;
    _requestedInitialLoad = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _loadAll();
    });
  }

  Future<List<EvaluationModelInfo>> _fetchModels() {
    return widget.debugFetchModels != null
        ? widget.debugFetchModels!()
        : eval_api.fetchEvaluationModels(context);
  }

  Future<EvaluationSummary> _fetchSummary() {
    return widget.debugFetchSummary != null
        ? widget.debugFetchSummary!()
        : eval_api.fetchEvaluationSummary(context);
  }

  Future<EvaluationRunHistoryPage> _fetchHistory({required int limit, required int offset}) {
    return widget.debugFetchHistory != null
        ? widget.debugFetchHistory!(limit: limit, offset: offset)
        : eval_api.fetchEvaluationHistory(context, limit: limit, offset: offset);
  }

  Future<EvaluationRunDetail> _fetchRunDetail(String runId) {
    return widget.debugFetchRunDetail != null
        ? widget.debugFetchRunDetail!(runId)
        : eval_api.fetchEvaluationRunDetail(context, runId);
  }

  Future<String> _startRun() {
    return widget.debugStartRun != null ? widget.debugStartRun!() : eval_api.startEvaluationRun(context);
  }

  Future<EvaluationConfusionMatrix?> _fetchMatrix({required String runId, required String component}) {
    return widget.debugFetchConfusionMatrix != null
        ? widget.debugFetchConfusionMatrix!(runId: runId, component: component)
        : eval_api.fetchEvaluationConfusionMatrix(context, runId: runId, component: component);
  }

  Future<EvaluationCaseResultsPage> _fetchCaseResults({
    required String runId,
    required String componentId,
    required int limit,
    required int offset,
  }) {
    return widget.debugFetchCaseResults != null
        ? widget.debugFetchCaseResults!(runId: runId, componentId: componentId, limit: limit, offset: offset)
        : eval_api.fetchEvaluationCaseResults(
            context, runId: runId, componentId: componentId, limit: limit, offset: offset);
  }

  Future<void> _loadAll() async {
    setState(() {
      _initialLoading = true;
      _loadError = null;
    });
    try {
      final models = await _fetchModels();
      final summary = await _fetchSummary();
      final history = await _fetchHistory(limit: _kHistoryPageSize, offset: 0);
      if (!mounted) return;
      setState(() {
        _models = models;
        _summary = summary;
        _history = history;
        _historyOffset = 0;
      });
      final latestId = summary.latestRun?.runId;
      if (latestId != null && latestId.isNotEmpty) {
        await _selectRun(latestId, switchTab: false);
      }
    } catch (error) {
      if (!mounted) return;
      setState(() => _loadError = friendlyEvalError(error));
    } finally {
      if (mounted) setState(() => _initialLoading = false);
    }
  }

  Future<void> _selectRun(String runId, {bool switchTab = true}) async {
    setState(() {
      _selectedRunId = runId;
      _loadingRunDetail = true;
      _runDetailError = null;
      _matrixByComponent.clear();
    });
    try {
      final detail = await _fetchRunDetail(runId);
      if (!mounted) return;
      setState(() => _selectedRunDetail = detail);
      for (final component in detail.components) {
        if (!component.hasConfusionMatrix) continue;
        final matrix = await _fetchMatrix(runId: runId, component: component.component);
        if (matrix != null && mounted) {
          setState(() => _matrixByComponent[component.component] = matrix);
        }
      }
      if (detail.summary.status == 'running') {
        _schedulePoll(runId);
      } else {
        _pollTimer?.cancel();
      }
    } on TimeoutException {
      if (!mounted) return;
      setState(() {
        _runDetailError = null;
        _selectedRunDetail ??= EvaluationRunDetail(
          summary: EvaluationRunSummary(
            runId: runId,
            status: 'running',
            startedAt: DateTime.now().toUtc().toIso8601String(),
          ),
          config: const {},
          components: const [],
        );
      });
      _schedulePoll(runId);
    } catch (error) {
      if (!mounted) return;
      setState(() => _runDetailError = friendlyEvalError(error));
    } finally {
      if (mounted) setState(() => _loadingRunDetail = false);
    }
    if (switchTab && mounted) {
      _tabController.animateTo(2);
    }
  }

  void _schedulePoll(String runId) {
    _pollTimer?.cancel();
    _pollTimer = Timer(const Duration(seconds: 4), () {
      if (!mounted || _selectedRunId != runId) return;
      _selectRun(runId, switchTab: false);
    });
  }

  Future<void> _onRunEvaluation() async {
    setState(() => _startingRun = true);
    try {
      final runId = await _startRun();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Evaluation run started.')),
      );
      final history = await _fetchHistory(limit: _kHistoryPageSize, offset: 0);
      if (mounted) {
        setState(() {
          _history = history;
          _historyOffset = 0;
        });
      }
      if (mounted) {
        setState(() {
          _selectedRunId = runId;
          _runDetailError = null;
          _selectedRunDetail = EvaluationRunDetail(
            summary: EvaluationRunSummary(
              runId: runId,
              status: 'running',
              startedAt: DateTime.now().toUtc().toIso8601String(),
            ),
            config: const {},
            components: const [],
          );
        });
        _tabController.animateTo(2);
      }
      _schedulePoll(runId);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(friendlyEvalError(error))),
      );
    } finally {
      if (mounted) setState(() => _startingRun = false);
    }
  }

  Future<void> _changeHistoryPage(int offset) async {
    try {
      final history = await _fetchHistory(limit: _kHistoryPageSize, offset: offset);
      if (!mounted) return;
      setState(() {
        _history = history;
        _historyOffset = offset;
      });
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(friendlyEvalError(error))));
    }
  }

  Future<void> _exportSelectedRun() async {
    final detail = _selectedRunDetail;
    if (detail == null) return;
    final text = buildEvalRunReportText(detail);
    await Clipboard.setData(ClipboardData(text: text));
    await downloadTextFile(
      filename: 'aska_evaluation_run_${detail.summary.runId}.txt',
      text: text,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Evaluation report copied and downloaded.')),
    );
  }

  void _openCaseResults(EvaluationComponentResult component) {
    final runId = _selectedRunId;
    if (runId == null) return;
    showDialog<void>(
      context: context,
      builder: (dialogContext) => _CaseResultsDialog(
        component: component,
        fetchPage: ({required int limit, required int offset}) => _fetchCaseResults(
          runId: runId,
          componentId: component.componentId,
          limit: limit,
          offset: offset,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final detail = _selectedRunDetail;
    final components = detail?.components ?? const <EvaluationComponentResult>[];

    return AdminScaffold(
      current: StudentNavItem.adminModelEvaluation,
      title: 'Model Evaluation',
      description: 'Run and review automated evaluation of every AI component ASKa-Piyu uses.',
      fillBody: true,
      showHeader: false,
      child: ColoredBox(
        color: DesignTokens.adminSurface,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _EvalHeader(
              onRefresh: _initialLoading ? null : _loadAll,
              onRun: _startingRun ? null : _onRunEvaluation,
              running: _startingRun,
            ),
            if (_initialLoading)
              const LinearProgressIndicator(minHeight: 3, key: Key('eval-initial-loading')),
            if (_loadError != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
                child: EvalNotice(message: _loadError!, key: const Key('eval-load-error')),
              ),
            Material(
              color: Colors.white,
              child: TabBar(
                controller: _tabController,
                isScrollable: true,
                labelColor: DesignTokens.maroon,
                unselectedLabelColor: DesignTokens.muted,
                indicatorColor: DesignTokens.maroon,
                tabs: [for (final title in _kEvalTabTitles) Tab(text: title)],
              ),
            ),
            Expanded(
              child: TabBarView(
                controller: _tabController,
                children: [
                  _OverviewTab(
                    summary: _summary,
                    detail: detail,
                    loading: _initialLoading,
                    onExport: detail == null ? null : _exportSelectedRun,
                  ),
                  _ModelsTab(models: _models, loading: _initialLoading),
                  _RunScopedTab(
                    runId: _selectedRunId,
                    status: detail?.summary.status,
                    loading: _loadingRunDetail,
                    error: _runDetailError,
                    child: _ComponentResultsTab(
                      components: components,
                      runStatus: detail?.summary.status,
                      onViewCases: _openCaseResults,
                    ),
                  ),
                  _RunScopedTab(
                    runId: _selectedRunId,
                    status: detail?.summary.status,
                    loading: _loadingRunDetail,
                    error: _runDetailError,
                    child: _ComparisonTab(
                      components: components,
                      matrices: _matrixByComponent,
                      config: detail?.config ?? const {},
                    ),
                  ),
                  _RunScopedTab(
                    runId: _selectedRunId,
                    status: detail?.summary.status,
                    loading: _loadingRunDetail,
                    error: _runDetailError,
                    child: _ConfusionMatricesTab(
                      components: components,
                      matrices: _matrixByComponent,
                    ),
                  ),
                  _RunScopedTab(
                    runId: _selectedRunId,
                    status: detail?.summary.status,
                    loading: _loadingRunDetail,
                    error: _runDetailError,
                    child: _PerformanceTab(components: components),
                  ),
                  _HistoryTab(
                    history: _history,
                    offset: _historyOffset,
                    pageSize: _kHistoryPageSize,
                    selectedRunId: _selectedRunId,
                    onSelectRun: (runId) => _selectRun(runId),
                    onChangePage: _changeHistoryPage,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String friendlyEvalError(Object error) {
  if (error is TimeoutException) {
    return 'The evaluation is still running. Use Refresh after it finishes to load metrics.';
  }
  final message = error.toString().trim();
  return message.isEmpty ? 'The backend did not return a usable response.' : message;
}

String buildEvalRunReportText(EvaluationRunDetail detail) {
  final buffer = StringBuffer();
  buffer.writeln('ASKa-Piyu Model Evaluation Report');
  buffer.writeln('Run ID: ${detail.summary.runId}');
  buffer.writeln('Status: ${detail.summary.status}');
  buffer.writeln('Started: ${detail.summary.startedAt}');
  if (detail.summary.completedAt != null) buffer.writeln('Completed: ${detail.summary.completedAt}');
  if (detail.summary.errorMessage != null) buffer.writeln('Error: ${detail.summary.errorMessage}');
  buffer.writeln('');
  buffer.writeln('Configuration:');
  for (final entry in detail.config.entries) {
    buffer.writeln('  ${entry.key}: ${entry.value}');
  }
  buffer.writeln('');
  for (final component in detail.components) {
    buffer.writeln('--- ${component.component} ---');
    buffer.writeln('Status: ${component.status}');
    if (component.reason != null) buffer.writeln('Reason: ${component.reason}');
    if (component.note != null) buffer.writeln('Note: ${component.note}');
    buffer.writeln(
      'Model: ${component.modelName}'
      '${component.sharesModelWith != null ? " (shares model with ${component.sharesModelWith})" : ""}',
    );
    buffer.writeln('Cases used: ${component.caseCount} · Unlabeled excluded: ${component.skippedUnlabeledCount}');
    for (final metric in component.metrics) {
      buffer.writeln('  ${metric.metricName}: ${metric.metricValue?.toStringAsFixed(4) ?? "N/A"}');
    }
    buffer.writeln('');
  }
  return buffer.toString();
}

// --- shared small widgets -----------------------------------------------

class _EvalHeader extends StatelessWidget {
  const _EvalHeader({required this.onRefresh, required this.onRun, required this.running});

  final VoidCallback? onRefresh;
  final VoidCallback? onRun;
  final bool running;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
      child: Wrap(
        spacing: 10,
        runSpacing: 10,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          const Text(
            'Model Evaluation',
            style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900, color: DesignTokens.ink),
          ),
          const SizedBox(width: 4),
          OutlinedButton.icon(
            key: const Key('eval-refresh-button'),
            onPressed: onRefresh,
            icon: const Icon(Icons.refresh_rounded, size: 18),
            label: const Text('Refresh'),
          ),
          ElevatedButton.icon(
            key: const Key('eval-run-button'),
            onPressed: onRun,
            icon: running
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Icon(Icons.play_arrow_rounded, size: 18),
            label: Text(running ? 'Starting...' : 'Run Evaluation'),
            style: ElevatedButton.styleFrom(
              backgroundColor: DesignTokens.maroon,
              foregroundColor: Colors.white,
            ),
          ),
        ],
      ),
    );
  }
}

class EvalNotice extends StatelessWidget {
  const EvalNotice({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF4E5),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFF5CBA7)),
      ),
      child: Row(
        children: [
          const Icon(Icons.info_outline_rounded, size: 18, color: Color(0xFF9A5B13)),
          const SizedBox(width: 8),
          Expanded(child: Text(message, style: const TextStyle(color: Color(0xFF9A5B13), fontSize: 13))),
        ],
      ),
    );
  }
}

class StatusBadge extends StatelessWidget {
  const StatusBadge({super.key, required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final (bg, fg, label) = switch (status) {
      'evaluated' => (const Color(0xFFDCFCE7), const Color(0xFF166534), 'Evaluated'),
      'completed' => (const Color(0xFFDCFCE7), const Color(0xFF166534), 'Completed'),
      'not_evaluable' => (const Color(0xFFF3F4F6), const Color(0xFF4B5563), 'Not evaluable'),
      'failed' => (const Color(0xFFFEE2E2), const Color(0xFFB91C1C), 'Failed'),
      'running' => (const Color(0xFFDBEAFE), const Color(0xFF1D4ED8), 'Running'),
      'pending' => (const Color(0xFFF3F4F6), const Color(0xFF4B5563), 'Pending Evaluation'),
      _ => (const Color(0xFFF3F4F6), const Color(0xFF4B5563), status),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
      child: Text(
        label,
        style: TextStyle(color: fg, fontWeight: FontWeight.w800, fontSize: 11),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.icon, required this.title, required this.description});

  final IconData icon;
  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 40, color: DesignTokens.muted),
            const SizedBox(height: 12),
            Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15, color: DesignTokens.ink)),
            const SizedBox(height: 6),
            Text(
              description,
              textAlign: TextAlign.center,
              style: const TextStyle(color: DesignTokens.muted, fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }
}

/// Wraps a tab's content with the loading/error/"no run selected" states
/// shared by every tab that depends on `_selectedRunDetail`.
class _RunScopedTab extends StatelessWidget {
  const _RunScopedTab({
    required this.runId,
    required this.status,
    required this.loading,
    required this.error,
    required this.child,
  });

  final String? runId;
  final String? status;
  final bool loading;
  final String? error;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (error != null) {
      return Padding(padding: const EdgeInsets.all(20), child: EvalNotice(message: error!));
    }
    if (runId == null) {
      return const _EmptyState(
        icon: Icons.science_outlined,
        title: 'No evaluation run yet',
        description: 'Run an evaluation, or pick one from History, to see results here.',
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          key: const Key('eval-viewing-run-banner'),
          color: DesignTokens.bgGrey,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          child: Row(
            children: [
              const Text('Viewing run: ', style: TextStyle(color: DesignTokens.muted, fontSize: 12, fontWeight: FontWeight.w700)),
              Text(runId!, style: const TextStyle(color: DesignTokens.ink, fontSize: 12, fontWeight: FontWeight.w800)),
              const SizedBox(width: 8),
              if (status != null) StatusBadge(status: status!),
            ],
          ),
        ),
        Expanded(child: child),
      ],
    );
  }
}

// --- Overview -------------------------------------------------------------

class _OverviewTab extends StatelessWidget {
  const _OverviewTab({
    required this.summary,
    required this.detail,
    required this.loading,
    required this.onExport,
  });

  final EvaluationSummary? summary;
  final EvaluationRunDetail? detail;
  final bool loading;
  final VoidCallback? onExport;

  @override
  Widget build(BuildContext context) {
    if (loading && summary == null) {
      return const Center(child: CircularProgressIndicator());
    }
    final latest = detail?.summary ?? summary?.latestRun;
    final components = detail?.components ?? summary?.components ?? const [];
    final evaluated = components.where((c) => c.status == 'evaluated').length;
    final notEvaluable = components.where((c) => c.status == 'not_evaluable').length;
    final failed = components.where((c) => c.status == 'failed').length;
    final config = detail?.config ?? const {};
    final retrieval = _byName(components, 'reranker') ?? _byName(components, 'embedding_retrieval');
    final hit = retrieval?.metric('reranked_hit_at_k') ?? retrieval?.metric('embedding_hit_at_k');
    final mrr = retrieval?.metric('reranked_mrr') ?? retrieval?.metric('embedding_mrr');
    final ndcg = retrieval?.metric('reranked_ndcg_at_k') ?? retrieval?.metric('embedding_ndcg_at_k');
    final retrievalEvaluated = hit != null || mrr != null || ndcg != null;

    final question = _byName(components, 'classify_question');
    final questionAccuracy = question?.status == 'evaluated' ? question!.metric('accuracy') : null;
    final answer = _byName(components, 'answer_generation_llm');
    final verifier = _byName(components, 'citation_verifier_llm');
    final ragScored = (verifier?.metrics.any((m) => m.metricValue != null) ?? false) ||
        (answer?.metrics.any((m) =>
                m.metricValue != null &&
                {'answer_correctness', 'faithfulness', 'answer_relevancy', 'citation_set_precision', 'citation_accuracy'}
                    .contains(m.metricName)) ??
            false);
    final answerCorrectness = (answer?.status == 'evaluated' ? answer?.metric('answer_correctness') : null) ??
        (verifier?.status == 'evaluated' ? verifier?.metric('answer_correctness') : null);

    return SingleChildScrollView(
      key: const Key('eval-overview-tab'),
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (latest != null)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                StatusBadge(status: latest.status),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Text(
                        'Latest evaluation at a glance',
                        style: TextStyle(
                          color: DesignTokens.ink,
                          fontSize: 15,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      SizedBox(height: 2),
                      Text(
                        'Three checks: did we find the right pages, tag the right categories, and score generated answers?',
                        style: TextStyle(color: DesignTokens.muted, fontSize: 13, height: 1.35),
                      ),
                    ],
                  ),
                ),
                if (onExport != null)
                  OutlinedButton.icon(
                    key: const Key('eval-export-button'),
                    onPressed: onExport,
                    icon: const Icon(Icons.download_rounded, size: 18),
                    label: const Text('Export report'),
                  ),
              ],
            )
          else
            const Text(
              'No evaluation has been run yet. Metric cards stay pending until a run completes.',
              style: TextStyle(color: DesignTokens.muted, fontSize: 13),
            ),
          const SizedBox(height: 16),
          _AtAGlanceRow(
            retrievalHit: retrievalEvaluated ? hit : null,
            retrievalIsSnapshot: _isSavedRetrievalSnapshot(retrieval),
            classificationAccuracy: questionAccuracy,
            answersScored: ragScored,
            answerCorrectness: answerCorrectness,
          ),
          const SizedBox(height: 20),
          _RetrievalOverviewPanel(
            retrieval: retrieval,
            embedding: _byName(components, 'embedding_retrieval'),
            hit: hit,
            mrr: mrr,
            ndcg: ndcg,
            evaluated: retrievalEvaluated,
          ),
          const SizedBox(height: 16),
          ClassificationOverviewSection(
            components: components,
            config: config,
            title: 'Classification Evaluation',
          ),
          const SizedBox(height: 16),
          _AnswerGenerationOverviewSection(components: components),
          if (latest?.status == 'failed' && latest?.errorMessage != null) ...[
            const SizedBox(height: 16),
            EvalNotice(message: latest!.errorMessage!),
          ],
          if (latest != null) ...[
            const SizedBox(height: 16),
            _RunDetailsPanel(
              evaluated: evaluated,
              notEvaluable: notEvaluable,
              failed: failed,
              startedAt: latest.startedAt,
              completedAt: latest.completedAt,
              config: config,
            ),
          ],
        ],
      ),
    );
  }
}

String _percentLabel(double? value) {
  if (value == null) return '—';
  return '${(value * 100).toStringAsFixed(2)}%';
}

bool _isSavedRetrievalSnapshot(EvaluationComponentResult? retrieval) {
  if (retrieval == null) return false;
  for (final name in ['reranked_hit_at_k', 'embedding_hit_at_k']) {
    final extra = retrieval.metricRow(name)?.extra;
    if (extra is Map && (extra['not_live_chroma'] == true || extra['durable_overview_overlay'] == true)) {
      return true;
    }
  }
  final note = retrieval.note ?? '';
  return note.contains('Not a live') || note.contains('isolated 691-chunk');
}

class _AtAGlanceRow extends StatelessWidget {
  const _AtAGlanceRow({
    required this.retrievalHit,
    required this.retrievalIsSnapshot,
    required this.classificationAccuracy,
    required this.answersScored,
    this.answerCorrectness,
  });

  final double? retrievalHit;
  final bool retrievalIsSnapshot;
  final double? classificationAccuracy;
  final bool answersScored;
  final double? answerCorrectness;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 840;
        final cards = [
          _glanceCard(
            color: const Color(0xFF0F766E),
            icon: Icons.manage_search_rounded,
            label: 'Document retrieval',
            value: _percentLabel(retrievalHit),
            detail: retrievalHit == null
                ? 'Not scored yet'
                : (retrievalIsSnapshot
                    ? 'Saved 12-question benchmark snapshot — not live Heroku retrieval'
                    : 'Found a relevant page in the top 5'),
          ),
          _glanceCard(
            color: const Color(0xFF1D4ED8),
            icon: Icons.category_outlined,
            label: 'Category tagging',
            value: _percentLabel(classificationAccuracy),
            detail: classificationAccuracy == null
                ? 'Not scored yet'
                : 'Correct category on student questions',
          ),
          _glanceCard(
            color: answersScored ? const Color(0xFF166534) : const Color(0xFF6B7280),
            icon: Icons.chat_bubble_outline_rounded,
            label: 'Answer quality',
            value: answersScored
                ? (answerCorrectness != null ? _percentLabel(answerCorrectness) : 'Scored')
                : 'Not scored',
            detail: answersScored
                ? 'Human-scored live student chatbot answers'
                : 'Waiting on a labeled answer-quality set',
          ),
        ];
        if (!wide) {
          return Column(
            children: [
              for (var i = 0; i < cards.length; i++) ...[
                if (i > 0) const SizedBox(height: 10),
                cards[i],
              ],
            ],
          );
        }
        return Row(
          children: [
            for (var i = 0; i < cards.length; i++) ...[
              if (i > 0) const SizedBox(width: 12),
              Expanded(child: cards[i]),
            ],
          ],
        );
      },
    );
  }

  Widget _glanceCard({
    required Color color,
    required IconData icon,
    required String label,
    required String value,
    required String detail,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.04),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
          Container(
            width: 4,
            decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(99)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(icon, size: 15, color: color),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        label,
                        style: TextStyle(
                          color: color,
                          fontSize: 12,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  value,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontSize: 26,
                    fontWeight: FontWeight.w900,
                    height: 1.1,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  detail,
                  style: const TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.3),
                ),
              ],
            ),
          ),
        ],
        ),
      ),
    );
  }
}

class _RetrievalOverviewPanel extends StatelessWidget {
  const _RetrievalOverviewPanel({
    required this.retrieval,
    required this.embedding,
    required this.hit,
    required this.mrr,
    required this.ndcg,
    required this.evaluated,
  });

  final EvaluationComponentResult? retrieval;
  final EvaluationComponentResult? embedding;
  final double? hit;
  final double? mrr;
  final double? ndcg;
  final bool evaluated;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _OverviewSectionHeader(
            title: 'Retrieval Evaluation',
            titleKey: const Key('eval-retrieval-overview-title'),
            statusKey: const Key('eval-retrieval-overview-status'),
            status: evaluated ? 'evaluated' : 'pending',
            subtitle: evaluated && _isSavedRetrievalSnapshot(retrieval)
                ? 'Saved benchmark snapshot from isolated evaluation corpus run 131ba7a4. Not a live Heroku / production Chroma score.'
                : 'Did the chatbot find the right handbook or charter pages for the test questions?',
          ),
          const SizedBox(height: 16),
          if (!evaluated)
            const _PendingCallout(
              title: 'Retrieval is not scored yet',
              body: 'These numbers appear after a run finishes against the labeled 12-question set.',
            )
          else ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  _percentLabel(hit),
                  style: const TextStyle(
                    fontSize: 40,
                    fontWeight: FontWeight.w900,
                    color: DesignTokens.ink,
                    height: 1,
                  ),
                ),
                const SizedBox(width: 12),
                const Expanded(
                  child: Padding(
                    padding: EdgeInsets.only(bottom: 4),
                    child: Text(
                      'of the labeled questions had a relevant page in the top 5 results',
                      style: TextStyle(color: DesignTokens.muted, fontSize: 14, height: 1.35),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            _CompactStatRow(
              stats: [
                ('Hit@K', _metricOrDash(hit), 'Share of questions with a relevant hit in the top 5'),
                ('MRR', _metricOrDash(mrr), 'How high the first relevant result ranked'),
                ('nDCG@K', _metricOrDash(ndcg), 'Whether the best pages were ranked first'),
                ('Cases', '${retrieval!.caseCount}', 'Labeled retrieval questions in this run'),
              ],
            ),
            if ((retrieval?.note ?? '').trim().isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                retrieval?.note ?? '',
                style: const TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.35),
              ),
            ],
          ],
          if ((retrieval?.retrievalCases().isNotEmpty == true) ||
              (embedding?.retrievalCases().isNotEmpty == true)) ...[
            const SizedBox(height: 20),
            _RetrievalQuestionBreakdown(
              cases: retrieval?.retrievalCases().isNotEmpty == true
                  ? retrieval!.retrievalCases()
                  : embedding!.retrievalCases(),
            ),
          ],
        ],
      ),
    );
  }
}

class _RetrievalQuestionBreakdown extends StatelessWidget {
  const _RetrievalQuestionBreakdown({required this.cases});

  final List<RetrievalCaseScore> cases;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Per-question scores',
          key: Key('eval-retrieval-case-table-title'),
          style: TextStyle(fontWeight: FontWeight.w800, fontSize: 14, color: DesignTokens.ink),
        ),
        const SizedBox(height: 4),
        const Text(
          'Saved benchmark hits for the 12 labeled questions. Embedding-only vs reranked. Not live Heroku retrieval.',
          style: TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.35),
        ),
        const SizedBox(height: 12),
        for (var index = 0; index < cases.length; index++)
          _RetrievalQuestionRow(index: index + 1, caseScore: cases[index]),
      ],
    );
  }
}

class _RetrievalQuestionRow extends StatelessWidget {
  const _RetrievalQuestionRow({required this.index, required this.caseScore});

  final int index;
  final RetrievalCaseScore caseScore;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key('eval-retrieval-case-${caseScore.caseId}'),
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Q$index  ${caseScore.question}',
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              fontSize: 13,
              height: 1.35,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              _RetrievalHitChip(title: 'Embedding', hit: caseScore.embeddingHit),
              _RetrievalHitChip(title: 'Reranked', hit: caseScore.rerankedHit),
            ],
          ),
        ],
      ),
    );
  }
}

class _RetrievalHitChip extends StatelessWidget {
  const _RetrievalHitChip({required this.title, required this.hit});

  final String title;
  final bool? hit;

  @override
  Widget build(BuildContext context) {
    final label = hit == null ? '—' : (hit! ? 'Hit' : 'Miss');
    final color = hit == null
        ? DesignTokens.muted
        : (hit! ? const Color(0xFF166534) : const Color(0xFFB91C1C));
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        '$title · $label',
        style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _RunDetailsPanel extends StatelessWidget {
  const _RunDetailsPanel({
    required this.evaluated,
    required this.notEvaluable,
    required this.failed,
    required this.startedAt,
    required this.completedAt,
    required this.config,
  });

  final int evaluated;
  final int notEvaluable;
  final int failed;
  final String startedAt;
  final String? completedAt;
  final Map<String, dynamic> config;

  @override
  Widget build(BuildContext context) {
    final versions = config['dataset_versions'];
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: DesignTokens.border),
        ),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 16),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          title: const Text(
            'Run details',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 14, color: DesignTokens.ink),
          ),
          subtitle: Text(
            'Models, timestamps, and dataset versions  ·  $evaluated scored, $notEvaluable not ready, $failed failed',
            style: const TextStyle(color: DesignTokens.muted, fontSize: 12),
          ),
          children: [
            _StatGrid(
              columns: 2,
              stats: [
                ('Evaluated components', '$evaluated', null),
                ('Not evaluable', '$notEvaluable', null),
                ('Failed components', '$failed', null),
                ('Started', _formatTimestamp(startedAt), null),
                ('Completed', completedAt == null ? '—' : _formatTimestamp(completedAt!), null),
                if (config['groq_model'] != null) ('Answer-generation model', '${config['groq_model']}', 'Environment'),
                if (config['embedding_model_label'] != null)
                  ('Embedding model', '${config['embedding_model_label']}', 'Environment'),
                if (config['app_commit'] != null) ('App commit', '${config['app_commit']}', 'Provenance'),
              ],
            ),
            if (versions is Map) ...[
              const SizedBox(height: 8),
              const Align(
                alignment: Alignment.centerLeft,
                child: Text('Dataset versions', style: TextStyle(fontWeight: FontWeight.w800, color: DesignTokens.ink)),
              ),
              const SizedBox(height: 6),
              for (final entry in versions.entries)
                Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    '${entry.key}: ${entry.value}',
                    style: const TextStyle(color: DesignTokens.muted, fontSize: 13),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

class _OverviewSectionHeader extends StatelessWidget {
  const _OverviewSectionHeader({
    required this.title,
    required this.titleKey,
    required this.status,
    this.statusKey,
    this.subtitle,
    this.caseCount,
  });

  final String title;
  final Key titleKey;
  final Key? statusKey;
  final String status;
  final String? subtitle;
  final int? caseCount;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 10,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(
              title,
              key: titleKey,
              style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900, color: DesignTokens.ink),
            ),
            StatusBadge(key: statusKey, status: status),
            if (caseCount != null)
              Text('$caseCount cases', style: const TextStyle(color: DesignTokens.muted, fontSize: 12, fontWeight: FontWeight.w700)),
          ],
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 6),
          Text(subtitle!, style: const TextStyle(color: DesignTokens.muted, fontSize: 13)),
        ],
      ],
    );
  }
}

class _AnswerGenerationOverviewSection extends StatelessWidget {
  const _AnswerGenerationOverviewSection({required this.components});

  final List<EvaluationComponentResult> components;

  static const _metricCards = [
    ('Answer Correctness', 'answer_correctness', <String>[], 'eval-rag-card-answer-correctness'),
    ('Faithfulness', 'faithfulness', <String>[], 'eval-rag-card-faithfulness'),
    ('Answer Relevance', 'answer_relevancy', <String>['answer_relevance'], 'eval-rag-card-answer-relevance'),
    ('Citation Accuracy', 'citation_accuracy', <String>['citation_set_precision'], 'eval-rag-card-citation-accuracy'),
  ];

  @override
  Widget build(BuildContext context) {
    final answer = _byName(components, 'answer_generation_llm');
    final verifier = _byName(components, 'citation_verifier_llm');

    double? ragMetric(String name, List<String> aliases) {
      for (final metricName in [name, ...aliases]) {
        final value = verifier?.metric(metricName) ?? answer?.metric(metricName);
        if (value != null) return value;
      }
      return null;
    }

    EvaluationComponentResult? sourceFor(String name, List<String> aliases) {
      for (final metricName in [name, ...aliases]) {
        if (verifier?.hasMetric(metricName) == true) return verifier;
        if (answer?.hasMetric(metricName) == true) return answer;
      }
      return null;
    }

    final values = [
      for (final card in _metricCards) ragMetric(card.$2, card.$3),
    ];
    final hasAnyScore = values.any((value) => value != null);
    final scoredSource = verifier?.metrics.any((m) => m.metricValue != null) == true ? verifier : answer;
    final sectionStatus = hasAnyScore ? (scoredSource?.status ?? 'evaluated') : 'pending';
    final sectionCases = hasAnyScore ? scoredSource?.caseCount : null;
    final questionScores = (answer?.humanRagCases().isNotEmpty == true)
        ? answer!.humanRagCases()
        : (verifier?.humanRagCases() ?? const <HumanRagCaseScore>[]);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _OverviewSectionHeader(
            title: 'Answer Generation / RAG Evaluation',
            titleKey: const Key('eval-rag-overview-title'),
            statusKey: const Key('eval-rag-overview-status'),
            status: sectionStatus,
            caseCount: sectionCases,
            subtitle: hasAnyScore
                ? 'Human-scored from 12 live student chatbot answers. Two faculty-manual questions were excluded (role-gated).'
                : 'Student answers are not scored in this run. The labeled answer-quality dataset is still empty.',
          ),
          if (!hasAnyScore) ...[
            const SizedBox(height: 14),
            const _PendingCallout(
              title: 'No answer scores yet',
              body:
                  'The four cards below stay blank until a labeled RAG evaluation set is saved. This does not mean the chatbot failed — those cases have not been scored.',
            ),
          ],
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 900 ? 4 : constraints.maxWidth >= 560 ? 2 : 1;
              const gap = 12.0;
              final width = constraints.maxWidth;
              final cardWidth = columns == 1 ? width : (width - gap * (columns - 1)) / columns;
              return Wrap(
                spacing: gap,
                runSpacing: gap,
                children: [
                  for (final card in _metricCards)
                    SizedBox(
                      width: cardWidth,
                      child: _RagMetricCard(
                        cardKey: Key(card.$4),
                        title: card.$1,
                        value: ragMetric(card.$2, card.$3),
                        source: sourceFor(card.$2, card.$3),
                        explanation: switch (card.$1) {
                          'Answer Correctness' => 'Pass = 1, partial = 0.5, fail = 0 on 12 student-visible questions',
                          'Faithfulness' => 'Did the live answer invent fees, totals, or facts not in the sources?',
                          'Answer Relevance' => 'Did the live answer address the question asked?',
                          _ => 'Right document title on screenshots that showed sources — not gold chunk IDs',
                        },
                      ),
                    ),
                ],
              );
            },
          ),
          if (questionScores.isNotEmpty) ...[
            const SizedBox(height: 20),
            _RagQuestionBreakdown(cases: questionScores),
          ],
        ],
      ),
    );
  }
}

class _RagQuestionBreakdown extends StatelessWidget {
  const _RagQuestionBreakdown({required this.cases});

  final List<HumanRagCaseScore> cases;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Per-question scores',
          key: Key('eval-rag-case-table-title'),
          style: TextStyle(fontWeight: FontWeight.w800, fontSize: 14, color: DesignTokens.ink),
        ),
        const SizedBox(height: 4),
        const Text(
          'Each row is one live chatbot question. The four cards above are averages of the 12 student-visible rows. Faculty-only questions are listed but not counted.',
          style: TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.35),
        ),
        const SizedBox(height: 12),
        for (var index = 0; index < cases.length; index++)
          _RagQuestionRow(index: index + 1, caseScore: cases[index]),
      ],
    );
  }
}

class _RagQuestionRow extends StatelessWidget {
  const _RagQuestionRow({required this.index, required this.caseScore});

  final int index;
  final HumanRagCaseScore caseScore;

  @override
  Widget build(BuildContext context) {
    final excluded = !caseScore.included;
    return Container(
      key: Key('eval-rag-case-${caseScore.caseId}'),
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: excluded ? const Color(0xFFF8FAFC) : Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Q$index  ${caseScore.question}',
            style: TextStyle(
              fontWeight: FontWeight.w700,
              fontSize: 13,
              height: 1.35,
              color: excluded ? DesignTokens.muted : DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              _RagScoreChip(title: 'Correctness', dimension: caseScore.correctness, excluded: excluded),
              _RagScoreChip(title: 'Faithfulness', dimension: caseScore.faithfulness, excluded: excluded),
              _RagScoreChip(title: 'Relevance', dimension: caseScore.relevance, excluded: excluded),
              _RagScoreChip(title: 'Citation', dimension: caseScore.citation, excluded: excluded),
            ],
          ),
          if (caseScore.note != null && caseScore.note!.trim().isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(caseScore.note!, style: const TextStyle(color: DesignTokens.muted, fontSize: 11, height: 1.35)),
          ],
        ],
      ),
    );
  }
}

class _RagScoreChip extends StatelessWidget {
  const _RagScoreChip({required this.title, required this.dimension, required this.excluded});

  final String title;
  final HumanRagDimensionScore? dimension;
  final bool excluded;

  @override
  Widget build(BuildContext context) {
    final label = _chipLabel(dimension, excluded: excluded);
    final color = _chipColor(dimension, excluded: excluded);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        '$title · $label',
        style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700),
      ),
    );
  }
}

String _chipLabel(HumanRagDimensionScore? dimension, {required bool excluded}) {
  if (excluded || dimension == null) {
    return dimension?.label == 'role_gated' ? 'Excluded' : (dimension?.label.replaceAll('_', ' ') ?? '—');
  }
  final pretty = switch (dimension.label) {
    'pass' => 'Pass',
    'partial' => 'Partial',
    'fail' => 'Fail',
    'faithful' => 'Faithful',
    'mixed' => 'Mixed',
    'invented_or_garbled' => 'Invented',
    'addressed' => 'Addressed',
    'not_addressed' => 'Not addressed',
    'matched' => 'Match',
    'no_sources_visible' => 'No sources',
    'role_gated' => 'Excluded',
    final other => other.replaceAll('_', ' '),
  };
  if (dimension.score == null) return pretty;
  return '$pretty ${dimension.score!.toStringAsFixed(1)}';
}

Color _chipColor(HumanRagDimensionScore? dimension, {required bool excluded}) {
  if (excluded || dimension?.label == 'role_gated') return DesignTokens.muted;
  final score = dimension?.score;
  if (score == null) return DesignTokens.muted;
  if (score >= 0.999) return const Color(0xFF166534);
  if (score >= 0.5) return const Color(0xFFB45309);
  return const Color(0xFFB91C1C);
}

class _RagMetricCard extends StatelessWidget {
  const _RagMetricCard({
    required this.cardKey,
    required this.title,
    required this.value,
    required this.source,
    required this.explanation,
  });

  final Key cardKey;
  final String title;
  final double? value;
  final EvaluationComponentResult? source;
  final String explanation;

  @override
  Widget build(BuildContext context) {
    final evaluated = value != null;
    final statusLabel = switch (source?.status) {
      'evaluated' || null => 'Evaluated',
      'not_evaluable' => 'Not evaluable',
      'failed' => 'Failed',
      'running' => 'Running',
      final other => other,
    };
    final caption = evaluated
        ? (source == null ? statusLabel : '$statusLabel · ${source!.caseCount} cases')
        : 'Not yet evaluated';
    return Container(
      key: cardKey,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: evaluated ? Colors.white : const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: evaluated ? DesignTokens.border : const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: DesignTokens.muted, fontSize: 11, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          Text(
            _metricOrDash(value),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: evaluated ? DesignTokens.ink : const Color(0xFF94A3B8),
              fontSize: 22,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 6),
          Text(explanation, style: const TextStyle(color: DesignTokens.muted, fontSize: 11, height: 1.3)),
          const SizedBox(height: 4),
          Text(caption, style: const TextStyle(color: DesignTokens.muted, fontSize: 11)),
        ],
      ),
    );
  }
}

String _metricOrDash(double? value) {
  if (value == null) return '—';
  return value.toStringAsFixed(4);
}

class _PendingCallout extends StatelessWidget {
  const _PendingCallout({required this.title, required this.body});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.hourglass_empty_rounded, size: 18, color: DesignTokens.muted),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 13,
                    color: DesignTokens.ink,
                  ),
                ),
                const SizedBox(height: 4),
                Text(body, style: const TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.4)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CompactStatRow extends StatelessWidget {
  const _CompactStatRow({required this.stats});

  final List<(String, String, String?)> stats;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      decoration: BoxDecoration(
        color: DesignTokens.bgGrey,
        borderRadius: BorderRadius.circular(12),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 640;
          final items = [
            for (var i = 0; i < stats.length; i++)
              _compactStat(stats[i], showDivider: wide && i < stats.length - 1),
          ];
          if (wide) {
            return Row(
              children: [
                for (final item in items) Expanded(child: item),
              ],
            );
          }
          return Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final stat in stats)
                SizedBox(
                  width: (constraints.maxWidth - 8) / 2,
                  child: _compactStat(stat, showDivider: false),
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _compactStat((String, String, String?) stat, {required bool showDivider}) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        border: showDivider ? const Border(right: BorderSide(color: Color(0xFFE2E8F0))) : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            stat.$1,
            style: const TextStyle(color: DesignTokens.muted, fontSize: 11, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 4),
          Text(
            stat.$2,
            style: const TextStyle(color: DesignTokens.ink, fontSize: 18, fontWeight: FontWeight.w900, height: 1.1),
          ),
          if (stat.$3 != null) ...[
            const SizedBox(height: 4),
            Text(stat.$3!, style: const TextStyle(color: DesignTokens.muted, fontSize: 11, height: 1.3)),
          ],
        ],
      ),
    );
  }
}

String _formatTimestamp(String iso) {
  final parsed = DateTime.tryParse(iso);
  if (parsed == null) return iso;
  final local = parsed.toLocal();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${local.year}-${two(local.month)}-${two(local.day)} ${two(local.hour)}:${two(local.minute)}';
}

class _StatGrid extends StatelessWidget {
  const _StatGrid({required this.columns, required this.stats});

  final int columns;
  final List<(String, String, String?)> stats;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        const gap = 12.0;
        final width = constraints.maxWidth;
        final cardWidth = columns == 1 ? width : (width - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            for (final stat in stats)
              SizedBox(
                width: cardWidth,
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: DesignTokens.border),
                    boxShadow: DesignTokens.softShadow(),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(stat.$1, style: const TextStyle(color: DesignTokens.muted, fontSize: 11, fontWeight: FontWeight.w700)),
                      const SizedBox(height: 8),
                      Text(
                        stat.$2,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: DesignTokens.ink, fontSize: 22, fontWeight: FontWeight.w900),
                      ),
                      if (stat.$3 != null) ...[
                        const SizedBox(height: 6),
                        Text(stat.$3!, style: const TextStyle(color: DesignTokens.muted, fontSize: 11)),
                      ],
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

// --- Model Inventory --------------------------------------------------------

class _ModelsTab extends StatelessWidget {
  const _ModelsTab({required this.models, required this.loading});

  final List<EvaluationModelInfo> models;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    if (loading && models.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (models.isEmpty) {
      return const _EmptyState(
        icon: Icons.memory_rounded,
        title: 'No components configured',
        description: 'The evaluation system has no known AI components yet.',
      );
    }
    return ListView.separated(
      key: const Key('eval-models-tab'),
      padding: const EdgeInsets.all(20),
      itemCount: models.length,
      separatorBuilder: (_, __) => const SizedBox(height: 10),
      itemBuilder: (context, index) {
        final model = models[index];
        return Container(
          key: Key('eval-model-${model.component}'),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: DesignTokens.border),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(model.component, style: const TextStyle(fontWeight: FontWeight.w800, color: DesignTokens.ink)),
                    const SizedBox(height: 4),
                    Text(model.modelName, style: const TextStyle(color: DesignTokens.muted, fontSize: 13)),
                  ],
                ),
              ),
              Wrap(
                spacing: 6,
                children: [
                  if (model.sharesModelWith != null)
                    _InfoChip(text: 'shares model with ${model.sharesModelWith}'),
                  if (model.allowLlmFallback != null)
                    _InfoChip(text: model.allowLlmFallback! ? 'LLM fallback enabled' : 'LLM fallback disabled'),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: DesignTokens.bgGrey, borderRadius: BorderRadius.circular(8)),
      child: Text(text, style: const TextStyle(fontSize: 11, color: DesignTokens.muted, fontWeight: FontWeight.w600)),
    );
  }
}

// --- Component Results ------------------------------------------------------

class _ComponentResultsTab extends StatelessWidget {
  const _ComponentResultsTab({
    required this.components,
    required this.onViewCases,
    this.runStatus,
  });

  final List<EvaluationComponentResult> components;
  final ValueChanged<EvaluationComponentResult> onViewCases;
  final String? runStatus;

  @override
  Widget build(BuildContext context) {
    if (components.isEmpty) {
      if (runStatus == 'running') {
        return const _EmptyState(
          icon: Icons.hourglass_top_rounded,
          title: 'Evaluation is still running',
          description:
              'Metrics and graphs appear when the 12 retrieval queries finish. Keep this tab open; Refresh if it still says Running after a couple of minutes.',
        );
      }
      return const _EmptyState(
        icon: Icons.fact_check_outlined,
        title: 'No component results',
        description: 'This run has no component results to show.',
      );
    }
    return ListView.separated(
      key: const Key('eval-results-tab'),
      padding: const EdgeInsets.all(20),
      itemCount: components.length,
      separatorBuilder: (_, __) => const SizedBox(height: 12),
      itemBuilder: (context, index) {
        final component = components[index];
        return Container(
          key: Key('eval-result-${component.component}'),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: DesignTokens.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(component.component, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15, color: DesignTokens.ink)),
                  ),
                  StatusBadge(status: component.status),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                '${component.modelName}'
                '${component.sharesModelWith != null ? " · shares model with ${component.sharesModelWith}" : ""}',
                style: const TextStyle(color: DesignTokens.muted, fontSize: 12),
              ),
              const SizedBox(height: 6),
              Text(
                'Cases used: ${component.caseCount} · Unlabeled excluded: ${component.skippedUnlabeledCount}',
                style: const TextStyle(color: DesignTokens.muted, fontSize: 12),
              ),
              if (component.reason != null) ...[
                const SizedBox(height: 6),
                Text(component.reason!, style: const TextStyle(color: Color(0xFF9A5B13), fontSize: 12)),
              ],
              if (component.note != null) ...[
                const SizedBox(height: 4),
                Text(component.note!, style: const TextStyle(color: DesignTokens.muted, fontSize: 12, fontStyle: FontStyle.italic)),
              ],
              if (component.metrics.isNotEmpty) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 16,
                  runSpacing: 6,
                  children: [
                    for (final metric in component.metrics)
                      _MetricPill(name: metric.metricName, value: metric.metricValue),
                  ],
                ),
              ],
              const SizedBox(height: 10),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  key: Key('eval-view-cases-${component.component}'),
                  onPressed: component.caseCount == 0 ? null : () => onViewCases(component),
                  child: const Text('View case-level results'),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _MetricPill extends StatelessWidget {
  const _MetricPill({required this.name, required this.value});

  final String name;
  final double? value;

  @override
  Widget build(BuildContext context) {
    final v = value;
    final display = v == null ? 'N/A' : v.toStringAsFixed(v == v.roundToDouble() ? 0 : 4);
    return RichText(
      text: TextSpan(
        children: [
          TextSpan(text: '$name: ', style: const TextStyle(color: DesignTokens.muted, fontSize: 12, fontWeight: FontWeight.w600)),
          TextSpan(
            text: display,
            style: TextStyle(
              color: value == null ? DesignTokens.muted : DesignTokens.ink,
              fontSize: 12,
              fontWeight: FontWeight.w800,
              fontStyle: value == null ? FontStyle.italic : FontStyle.normal,
            ),
          ),
        ],
      ),
    );
  }
}

// --- Comparison -------------------------------------------------------------

EvaluationComponentResult? _byName(List<EvaluationComponentResult> components, String name) {
  for (final c in components) {
    if (c.component == name) return c;
  }
  return null;
}

class _ComparisonTab extends StatelessWidget {
  const _ComparisonTab({
    required this.components,
    required this.matrices,
    this.config = const {},
  });

  final List<EvaluationComponentResult> components;
  final Map<String, EvaluationConfusionMatrix> matrices;
  final Map<String, dynamic> config;

  @override
  Widget build(BuildContext context) {
    final reranker = _byName(components, 'reranker');
    final embedding = _byName(components, 'embedding_retrieval');

    return SingleChildScrollView(
      key: const Key('eval-comparison-tab'),
      padding: const EdgeInsets.all(20),
      child: Column(
        children: [
        EvalComparatorTable(
          title: 'Retrieval comparator',
          subtitle: 'Saved 12-question benchmark snapshot from isolated corpus run 131ba7a4. Not live Heroku / production Chroma.',
          rows: [
            EvalComparatorRow(
              label: 'Embedding-only',
              metrics: [
                EvalComparatorMetric(name: 'Hit@K', value: reranker?.metric('embedding_hit_at_k') ?? embedding?.metric('embedding_hit_at_k')),
                EvalComparatorMetric(name: 'MRR', value: reranker?.metric('embedding_mrr') ?? embedding?.metric('embedding_mrr')),
                EvalComparatorMetric(name: 'nDCG@K', value: reranker?.metric('embedding_ndcg_at_k') ?? embedding?.metric('embedding_ndcg_at_k')),
                EvalComparatorMetric(name: 'Precision@K', value: reranker?.metric('embedding_precision_at_k') ?? embedding?.metric('embedding_precision_at_k')),
                EvalComparatorMetric(name: 'Recall@K', value: reranker?.metric('embedding_recall_at_k') ?? embedding?.metric('embedding_recall_at_k')),
              ],
            ),
            EvalComparatorRow(
              label: 'Reranked',
              metrics: [
                EvalComparatorMetric(name: 'Hit@K', value: reranker?.metric('reranked_hit_at_k')),
                EvalComparatorMetric(name: 'MRR', value: reranker?.metric('reranked_mrr')),
                EvalComparatorMetric(name: 'nDCG@K', value: reranker?.metric('reranked_ndcg_at_k')),
                EvalComparatorMetric(name: 'Precision@K', value: reranker?.metric('reranked_precision_at_k')),
                EvalComparatorMetric(name: 'Recall@K', value: reranker?.metric('reranked_recall_at_k')),
              ],
            ),
          ],
        ),
        const SizedBox(height: 16),
        EvalBarChartCard(
          title: 'Retrieval: embedding-only vs reranked',
          subtitle: 'Same queries/labels for both rankings -- the delta is the reranker\'s measured contribution',
          bars: [
            EvalBarEntry(label: 'Hit@K\n(embed)', value: reranker?.metric('embedding_hit_at_k'), color: const Color(0xFF2563EB)),
            EvalBarEntry(label: 'Hit@K\n(reranked)', value: reranker?.metric('reranked_hit_at_k'), color: DesignTokens.maroon),
            EvalBarEntry(label: 'MRR\n(embed)', value: reranker?.metric('embedding_mrr'), color: const Color(0xFF2563EB)),
            EvalBarEntry(label: 'MRR\n(reranked)', value: reranker?.metric('reranked_mrr'), color: DesignTokens.maroon),
            EvalBarEntry(label: 'nDCG@K\n(embed)', value: reranker?.metric('embedding_ndcg_at_k'), color: const Color(0xFF2563EB)),
            EvalBarEntry(label: 'nDCG@K\n(reranked)', value: reranker?.metric('reranked_ndcg_at_k'), color: DesignTokens.maroon),
          ],
          maxY: 1.0,
        ),
        const SizedBox(height: 16),
        ClassificationOverviewSection(
          components: components,
          config: config,
        ),
        const SizedBox(height: 16),
        ClassificationClassifierSections(
          components: components,
          matrices: matrices,
        ),
        ],
      ),
    );
  }
}

// --- Confusion Matrices ------------------------------------------------------

class _ConfusionMatricesTab extends StatelessWidget {
  const _ConfusionMatricesTab({required this.components, required this.matrices});

  final List<EvaluationComponentResult> components;
  final Map<String, EvaluationConfusionMatrix> matrices;

  @override
  Widget build(BuildContext context) {
    // Confusion matrices are meaningful ONLY for classification components
    // -- never shown for retrieval/RAG/performance components, even if a
    // caller somehow passed one in.
    final classificationComponents = components
        .where((c) => c.component.startsWith('classify_chunk') || c.component == 'classify_question')
        .toList();
    if (classificationComponents.isEmpty) {
      return const _EmptyState(
        icon: Icons.grid_on_rounded,
        title: 'No classification components in this run',
        description: 'Confusion matrices only apply to classify_chunk/classify_question.',
      );
    }
    return ListView(
      key: const Key('eval-confusion-tab'),
      padding: const EdgeInsets.all(20),
      children: [
        const EvalNotice(
          message:
              'Confusion matrices use this run’s saved classify_question / classify_chunk labels. Retrieval Hit@K / MRR / nDCG live on Overview and Comparison.',
        ),
        const SizedBox(height: 16),
        for (final component in classificationComponents) ...[
          if (matrices[component.component] != null)
            ConfusionMatrixGrid(matrix: matrices[component.component]!)
          else
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: DesignTokens.border),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(component.component, style: const TextStyle(fontWeight: FontWeight.w800, color: DesignTokens.ink)),
                  const SizedBox(height: 6),
                  Text(
                    component.status == 'evaluated'
                        ? 'No confusion matrix was returned for this component.'
                        : 'Not available (${component.status}${component.reason != null ? ": ${component.reason}" : ""}).',
                    style: const TextStyle(color: DesignTokens.muted, fontSize: 12),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 16),
        ],
      ],
    );
  }
}

// --- Performance --------------------------------------------------------------

class _PerformanceTab extends StatelessWidget {
  const _PerformanceTab({required this.components});

  final List<EvaluationComponentResult> components;

  @override
  Widget build(BuildContext context) {
    final answerLlm = _byName(components, 'answer_generation_llm');
    final verifierLlm = _byName(components, 'citation_verifier_llm');
    final hasAny = (answerLlm?.metrics.isNotEmpty ?? false) || (verifierLlm?.metrics.isNotEmpty ?? false);
    if (!hasAny) {
      return const _EmptyState(
        icon: Icons.speed_rounded,
        title: 'No performance metrics in this run',
        description: 'Latency/throughput metrics appear once answer_generation_llm or citation_verifier_llm runs.',
      );
    }
    return ListView(
      key: const Key('eval-performance-tab'),
      padding: const EdgeInsets.all(20),
      children: [
        EvalBarChartCard(
          title: 'Answer-generation latency (ms)',
          subtitle: 'Average vs first-call-in-run vs later (warm) calls',
          bars: [
            EvalBarEntry(label: 'Average', value: answerLlm?.metric('avg_latency_ms'), color: const Color(0xFF2563EB)),
            EvalBarEntry(label: 'First call\nin run', value: answerLlm?.metric('first_call_in_run_avg_latency_ms'), color: const Color(0xFFD97706)),
            EvalBarEntry(label: 'Warm', value: answerLlm?.metric('warm_avg_latency_ms'), color: const Color(0xFF16A34A)),
          ],
        ),
        const SizedBox(height: 16),
        EvalBarChartCard(
          title: 'Citation-verifier latency (ms)',
          subtitle: 'Average vs first-call-in-run vs later (warm) calls',
          bars: [
            EvalBarEntry(label: 'Average', value: verifierLlm?.metric('avg_latency_ms'), color: const Color(0xFF2563EB)),
            EvalBarEntry(label: 'First call\nin run', value: verifierLlm?.metric('first_call_in_run_avg_latency_ms'), color: const Color(0xFFD97706)),
            EvalBarEntry(label: 'Warm', value: verifierLlm?.metric('warm_avg_latency_ms'), color: const Color(0xFF16A34A)),
          ],
        ),
        const SizedBox(height: 16),
        EvalBarChartCard(
          title: 'Success rate',
          subtitle: 'Fraction of calls that succeeded',
          bars: [
            EvalBarEntry(label: 'Answer\ngeneration', value: answerLlm?.metric('success_rate'), color: DesignTokens.maroon),
            EvalBarEntry(label: 'Citation\nverifier', value: verifierLlm?.metric('success_rate'), color: const Color(0xFF2563EB)),
          ],
          maxY: 1.0,
        ),
      ],
    );
  }
}

// --- History -----------------------------------------------------------------

class _HistoryTab extends StatelessWidget {
  const _HistoryTab({
    required this.history,
    required this.offset,
    required this.pageSize,
    required this.selectedRunId,
    required this.onSelectRun,
    required this.onChangePage,
  });

  final EvaluationRunHistoryPage? history;
  final int offset;
  final int pageSize;
  final String? selectedRunId;
  final ValueChanged<String> onSelectRun;
  final ValueChanged<int> onChangePage;

  @override
  Widget build(BuildContext context) {
    final page = history;
    if (page == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (page.runs.isEmpty) {
      return const _EmptyState(
        icon: Icons.history_rounded,
        title: 'No evaluation runs yet',
        description: 'Runs will appear here once you use "Run Evaluation".',
      );
    }
    final canPrev = offset > 0;
    final canNext = offset + page.runs.length < page.total;
    return Column(
      key: const Key('eval-history-tab'),
      children: [
        Expanded(
          child: ListView.separated(
            padding: const EdgeInsets.all(20),
            itemCount: page.runs.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, index) {
              final run = page.runs[index];
              final selected = run.runId == selectedRunId;
              return InkWell(
                key: Key('eval-history-row-${run.runId}'),
                onTap: () => onSelectRun(run.runId),
                borderRadius: BorderRadius.circular(12),
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: selected ? const Color(0xFFFCEFF0) : Colors.white,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: selected ? DesignTokens.maroon : DesignTokens.border),
                  ),
                  child: Row(
                    children: [
                      StatusBadge(status: run.status),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(run.runId, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: DesignTokens.ink)),
                            const SizedBox(height: 2),
                            Text(
                              'Started ${_formatTimestamp(run.startedAt)}'
                              '${run.completedAt != null ? " · Completed ${_formatTimestamp(run.completedAt!)}" : ""}',
                              style: const TextStyle(color: DesignTokens.muted, fontSize: 12),
                            ),
                          ],
                        ),
                      ),
                      const Icon(Icons.chevron_right_rounded, color: DesignTokens.muted),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('${page.total} run${page.total == 1 ? '' : 's'} total', style: const TextStyle(color: DesignTokens.muted, fontSize: 12)),
              Row(
                children: [
                  TextButton(
                    onPressed: canPrev ? () => onChangePage((offset - pageSize).clamp(0, 1 << 30)) : null,
                    child: const Text('Previous'),
                  ),
                  TextButton(
                    onPressed: canNext ? () => onChangePage(offset + pageSize) : null,
                    child: const Text('Next'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// --- Case results dialog ------------------------------------------------------

class _CaseResultsDialog extends StatefulWidget {
  const _CaseResultsDialog({required this.component, required this.fetchPage});

  final EvaluationComponentResult component;
  final Future<EvaluationCaseResultsPage> Function({required int limit, required int offset}) fetchPage;

  @override
  State<_CaseResultsDialog> createState() => _CaseResultsDialogState();
}

class _CaseResultsDialogState extends State<_CaseResultsDialog> {
  static const int _pageSize = 20;
  int _offset = 0;
  EvaluationCaseResultsPage? _page;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await widget.fetchPage(limit: _pageSize, offset: _offset);
      if (!mounted) return;
      setState(() => _page = page);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = friendlyEvalError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final page = _page;
    return Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560, maxHeight: 560),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${widget.component.component} — case results',
                      style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16, color: DesignTokens.ink),
                    ),
                  ),
                  IconButton(onPressed: () => Navigator.of(context).pop(), icon: const Icon(Icons.close_rounded)),
                ],
              ),
              const SizedBox(height: 8),
              if (_loading) const LinearProgressIndicator(minHeight: 3),
              if (_error != null) EvalNotice(message: _error!),
              if (page != null)
                Expanded(
                  child: page.caseResults.isEmpty
                      ? const Center(child: Text('No case results on this page.'))
                      : ListView.separated(
                          key: const Key('eval-case-results-list'),
                          itemCount: page.caseResults.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (context, index) {
                            final item = page.caseResults[index];
                            return ListTile(
                              dense: true,
                              contentPadding: EdgeInsets.zero,
                              title: Text(item.caseId, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
                              subtitle: Text(
                                'predicted: ${item.predicted ?? "N/A"}'
                                '${item.expected != null ? " · expected: ${item.expected}" : ""}'
                                '${item.correct != null ? " · correct: ${item.correct}" : ""}'
                                '${item.latencyMs != null ? " · ${item.latencyMs!.toStringAsFixed(0)}ms" : ""}',
                                style: const TextStyle(fontSize: 12),
                              ),
                            );
                          },
                        ),
                ),
              if (page != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('${page.total} case${page.total == 1 ? '' : 's'} total', style: const TextStyle(color: DesignTokens.muted, fontSize: 12)),
                      Row(
                        children: [
                          TextButton(
                            onPressed: _offset > 0
                                ? () {
                                    setState(() => _offset = (_offset - _pageSize).clamp(0, 1 << 30));
                                    _load();
                                  }
                                : null,
                            child: const Text('Previous'),
                          ),
                          TextButton(
                            onPressed: _offset + page.caseResults.length < page.total
                                ? () {
                                    setState(() => _offset += _pageSize);
                                    _load();
                                  }
                                : null,
                            child: const Text('Next'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
