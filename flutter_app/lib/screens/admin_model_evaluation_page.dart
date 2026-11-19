/// Admin Model Evaluation screen.
///
/// Numbers come from /admin/evaluation/* APIs. Tests can inject
/// debugFetch* / debugStartRun seams instead of real HTTP.
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
typedef FetchQaCitationOverview = Future<QaCitationJudgingOverview> Function();
typedef FetchFullReport = Future<Map<String, dynamic>> Function();

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
    this.debugFetchQaCitationOverview,
    this.debugFetchFullReport,
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
  @visibleForTesting
  final FetchQaCitationOverview? debugFetchQaCitationOverview;
  @visibleForTesting
  final FetchFullReport? debugFetchFullReport;

  @override
  State<AdminModelEvaluationPage> createState() => _AdminModelEvaluationPageState();
}

class _AdminModelEvaluationPageState extends State<AdminModelEvaluationPage> {
  bool _initialLoading = false;
  bool _requestedInitialLoad = false;
  String? _loadError;

  EvaluationSummary? _summary;
  QaCitationJudgingOverview? _qaCitationOverview;
  String? _qaCitationOverviewError;
  bool _qaCitationOverviewLoading = false;

  String? _selectedRunId;
  EvaluationRunDetail? _selectedRunDetail;
  final Map<String, EvaluationConfusionMatrix> _matrixByComponent = {};

  bool _startingRun = false;
  Timer? _pollTimer;

  @override
  void dispose() {
    _pollTimer?.cancel();
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

  Future<EvaluationSummary> _fetchSummary() {
    return widget.debugFetchSummary != null
        ? widget.debugFetchSummary!()
        : eval_api.fetchEvaluationSummary(context);
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

  Future<QaCitationJudgingOverview> _fetchQaCitationOverview() {
    return widget.debugFetchQaCitationOverview != null
        ? widget.debugFetchQaCitationOverview!()
        : eval_api.fetchQaCitationJudgingOverview(context);
  }

  Future<void> _loadQaCitationOverview() async {
    setState(() {
      _qaCitationOverviewLoading = true;
      _qaCitationOverviewError = null;
    });
    try {
      final overview = await _fetchQaCitationOverview();
      if (!mounted) return;
      setState(() => _qaCitationOverview = overview);
    } catch (error) {
      if (!mounted) return;
      // Degrade honestly: this section's own load failure never blocks or
      // fabricates data for the rest of the dashboard.
      setState(() => _qaCitationOverviewError = friendlyEvalError(error));
    } finally {
      if (mounted) setState(() => _qaCitationOverviewLoading = false);
    }
  }

  Future<void> _loadAll() async {
    setState(() {
      _initialLoading = true;
      _loadError = null;
    });
    try {
      final summary = await _fetchSummary();
      if (!mounted) return;
      setState(() {
        _summary = summary;
      });
      final latestId = summary.latestRun?.runId;
      if (latestId != null && latestId.isNotEmpty) {
        await _selectRun(latestId, switchTab: false);
      }
      unawaited(_loadQaCitationOverview());
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
      // Each section below degrades gracefully on its own (pending/empty
      // states) when `_selectedRunDetail` stays unset -- this previously
      // also surfaced via Section 7's "Viewing run" banner, which the
      // dashboard-cleanup pass removed along with the rest of Section 7.
      if (!mounted) return;
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
      if (mounted) {
        setState(() {
          _selectedRunId = runId;
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
            Expanded(
              child: SingleChildScrollView(
                key: const Key('eval-report-scroll'),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _EvaluationOverviewSection(
                      summary: _summary,
                      detail: detail,
                      loading: _initialLoading,
                      onExport: detail == null ? null : _exportSelectedRun,
                      qaCitationOverview: _qaCitationOverview,
                      qaCitationOverviewLoading: _qaCitationOverviewLoading,
                      qaCitationOverviewError: _qaCitationOverviewError,
                    ),
                    _ClassificationResultsSection(
                      components: components,
                      matrices: _matrixByComponent,
                      config: detail?.config ?? const {},
                    ),
                    _RetrievalEvaluationSection(components: components),
                    _QaEvaluationSection(
                      components: components,
                      overview: _qaCitationOverview,
                      loading: _qaCitationOverviewLoading,
                      error: _qaCitationOverviewError,
                      onRetry: _loadQaCitationOverview,
                    ),
                    _CitationGroundingSection(
                      overview: _qaCitationOverview,
                      loading: _qaCitationOverviewLoading,
                      error: _qaCitationOverviewError,
                      onRetry: _loadQaCitationOverview,
                    ),
                    const _MethodologySection(),
                    const SizedBox(height: 24),
                  ],
                ),
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
      'running' => (DesignTokens.maroonWash, DesignTokens.maroon, 'Running'),
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

/// Big numbered heading for one of the report's 7 top-level sections.
class _ReportSectionHeading extends StatelessWidget {
  const _ReportSectionHeading({required this.number, required this.title, required this.subtitle, this.sectionKey});

  final int number;
  final String title;
  final String subtitle;
  final Key? sectionKey;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: sectionKey,
      padding: const EdgeInsets.fromLTRB(20, 28, 20, 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 32,
                height: 32,
                alignment: Alignment.center,
                decoration: BoxDecoration(color: DesignTokens.maroon, borderRadius: BorderRadius.circular(8)),
                child: Text('$number', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: 15)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900, color: DesignTokens.ink)),
                    const SizedBox(height: 2),
                    Text(subtitle, style: const TextStyle(color: DesignTokens.muted, fontSize: 13, height: 1.35)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          const Divider(height: 1),
        ],
      ),
    );
  }
}

// --- Overview -------------------------------------------------------------

/// Section 1: "Evaluation Overview". A short at-a-glance summary only --
/// the full Classification/Retrieval/QA/Citation panels live in their own
/// numbered sections below (2-5); this section never duplicates their
/// detail, only teases it.
class _EvaluationOverviewSection extends StatelessWidget {
  const _EvaluationOverviewSection({
    required this.summary,
    required this.detail,
    required this.loading,
    required this.onExport,
    required this.qaCitationOverview,
    required this.qaCitationOverviewLoading,
    required this.qaCitationOverviewError,
  });

  final EvaluationSummary? summary;
  final EvaluationRunDetail? detail;
  final bool loading;
  final VoidCallback? onExport;
  final QaCitationJudgingOverview? qaCitationOverview;
  final bool qaCitationOverviewLoading;
  final String? qaCitationOverviewError;

  @override
  Widget build(BuildContext context) {
    final body = loading && summary == null
        ? const Padding(
            padding: EdgeInsets.all(20),
            child: Center(child: CircularProgressIndicator()),
          )
        : _buildContent(context);
    return Column(
      key: const Key('eval-overview-section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _ReportSectionHeading(
          number: 1,
          title: 'Evaluation Overview',
          subtitle: 'A quick summary of the latest run. Full detail for each area is in the sections below.',
          sectionKey: Key('eval-section-1-overview'),
        ),
        Padding(padding: const EdgeInsets.fromLTRB(20, 16, 20, 0), child: body),
      ],
    );
  }

  Widget _buildContent(BuildContext context) {
    final latest = detail?.summary ?? summary?.latestRun;
    final components = detail?.components ?? summary?.components ?? const [];
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

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (latest != null)
          LayoutBuilder(
            builder: (context, constraints) {
              final narrow = constraints.maxWidth < 480;
              final badgeAndText = Row(
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
                  if (onExport != null && !narrow)
                    OutlinedButton.icon(
                      key: const Key('eval-export-button'),
                      onPressed: onExport,
                      icon: const Icon(Icons.download_rounded, size: 18),
                      label: const Text('Export report'),
                    ),
                ],
              );
              if (!narrow || onExport == null) return badgeAndText;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  badgeAndText,
                  const SizedBox(height: 10),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: OutlinedButton.icon(
                      key: const Key('eval-export-button'),
                      onPressed: onExport,
                      icon: const Icon(Icons.download_rounded, size: 18),
                      label: const Text('Export report'),
                    ),
                  ),
                ],
              );
            },
          )
        else
          const Text(
            'No evaluation has been run yet. Metric cards stay pending until a run completes.',
            style: TextStyle(color: DesignTokens.muted, fontSize: 13),
          ),
        const SizedBox(height: 16),
        _AtAGlanceRow(
          retrievalHit: retrievalEvaluated ? hit : null,
          classificationAccuracy: questionAccuracy,
          answersScored: ragScored,
          answerCorrectness: answerCorrectness,
        ),
        const SizedBox(height: 20),
        _QaCitationOverviewSummary(
          overview: qaCitationOverview,
          loading: qaCitationOverviewLoading,
          error: qaCitationOverviewError,
        ),
        if (latest?.status == 'failed' && latest?.errorMessage != null) ...[
          const SizedBox(height: 16),
          EvalNotice(message: latest!.errorMessage!),
        ],
      ],
    );
  }
}

/// Concise Overview-section summary of the Stage 3.2B-3.6 QA/citation
/// judging results. Reuses the same already-fetched `QaCitationJudgingOverview`
/// object Sections 4 ("QA Evaluation") and 5 ("Citation and Grounding
/// Evaluation") render in full -- no second fetch, no duplicated backend
/// call, no hardcoded metric values. Degrades honestly (loading/error/
/// empty) exactly like those sections do, independent of the rest of
/// Overview's own loading state, since this data loads separately.
class _QaCitationOverviewSummary extends StatelessWidget {
  const _QaCitationOverviewSummary({
    required this.overview,
    required this.loading,
    required this.error,
  });

  final QaCitationJudgingOverview? overview;
  final bool loading;
  final String? error;

  @override
  Widget build(BuildContext context) {
    if (loading && overview == null && error == null) {
      return const Padding(
        key: Key('eval-overview-qa-citation-loading'),
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Row(
          children: [
            SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
            SizedBox(width: 10),
            Text('Loading QA and citation judging summary...',
                style: TextStyle(color: DesignTokens.muted, fontSize: 12)),
          ],
        ),
      );
    }
    if (error != null && overview == null) {
      return EvalNotice(
        key: const Key('eval-overview-qa-citation-error'),
        message: 'QA and citation summary unavailable: $error',
      );
    }
    final data = overview;
    if (data == null || !data.available) {
      return const _PendingCallout(
        key: Key('eval-overview-qa-citation-empty'),
        title: 'QA and citation judging results are not available',
        body: 'See "QA Evaluation" and "Citation and Grounding Evaluation" below once the Stage 3.2B-3.6 artifacts are available.',
      );
    }

    return Column(
      key: const Key('eval-overview-qa-citation-summary'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _OverviewSectionHeader(
          title: 'QA & Citation',
          titleKey: const Key('eval-overview-qa-citation-title'),
          status: 'evaluated',
          subtitle: 'Full breakdown, disagreement, and limitations are in "QA Evaluation" and "Citation and Grounding Evaluation" below.',
        ),
        const SizedBox(height: 12),
        LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth >= 900 ? 6 : constraints.maxWidth >= 560 ? 3 : 1;
            const gap = 12.0;
            final width = constraints.maxWidth;
            final cardWidth = columns == 1 ? width : (width - gap * (columns - 1)) / columns;
            return Wrap(
              spacing: gap,
              runSpacing: gap,
              children: [
                SizedBox(
                  width: cardWidth,
                  child: _ScaleMetricCard(
                    cardKey: const Key('eval-overview-qa-overall'),
                    title: 'QA Overall',
                    value: data.qaOverall,
                    scaleMax: 4,
                  ),
                ),
                SizedBox(
                  width: cardWidth,
                  child: _FractionMetricCard(
                    cardKey: const Key('eval-overview-citation-precision'),
                    title: 'Citation Precision',
                    fraction: data.citationPrecision,
                  ),
                ),
                SizedBox(
                  width: cardWidth,
                  child: _FractionMetricCard(
                    cardKey: const Key('eval-overview-citation-completeness'),
                    title: 'Citation Completeness',
                    fraction: data.citationCompleteness,
                  ),
                ),
                SizedBox(
                  width: cardWidth,
                  child: _FractionMetricCard(
                    cardKey: const Key('eval-overview-citation-validity'),
                    title: 'Citation Validity (corrected)',
                    fraction: data.citationValidityCorrected,
                    highlight: true,
                  ),
                ),
              ],
            );
          },
        ),
        const SizedBox(height: 10),
        Text(
          key: const Key('eval-overview-qa-citation-counts'),
          'QA: ${data.qaJudgedCount ?? 0} fully judged answerable cases.  '
          'Citation: ${data.citationJudgedCaseCount ?? 0} fully judged cases, '
          '${data.citationJudgingFailedPartialCount ?? 0} partial judging failure(s).',
          style: const TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.4),
        ),
      ],
    );
  }
}

/// Section 2: "Classification Results". Consolidates the former
/// "Comparison" tab's classification half and the former "Confusion
/// Matrices" tab's classify_question/classify_chunk matrices --
/// [ClassificationClassifierSections] already renders each classifier's
/// confusion matrix inline (admin_model_evaluation_classification.dart),
/// so no separate matrix listing is needed here.
class _ClassificationResultsSection extends StatelessWidget {
  const _ClassificationResultsSection({
    required this.components,
    required this.matrices,
    required this.config,
  });

  final List<EvaluationComponentResult> components;
  final Map<String, EvaluationConfusionMatrix> matrices;
  final Map<String, dynamic> config;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('eval-classification-section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _ReportSectionHeading(
          number: 2,
          title: 'Classification Results',
          subtitle: 'Did the system assign the right category to student questions and handbook passages, including confusion matrices per classifier?',
          sectionKey: Key('eval-section-2-classification'),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ClassificationOverviewSection(components: components, config: config, title: 'Classification Evaluation'),
              const SizedBox(height: 16),
              ClassificationClassifierSections(components: components, matrices: matrices),
            ],
          ),
        ),
      ],
    );
  }
}

/// Section 3: "Retrieval Evaluation". Consolidates the former Overview
/// tab's retrieval panel plus the former "Comparison" tab's
/// embedding-vs-reranked retrieval comparator and bar chart.
class _RetrievalEvaluationSection extends StatelessWidget {
  const _RetrievalEvaluationSection({required this.components});

  final List<EvaluationComponentResult> components;

  @override
  Widget build(BuildContext context) {
    final reranker = _byName(components, 'reranker');
    final embedding = _byName(components, 'embedding_retrieval');
    final retrieval = reranker ?? embedding;
    final hit = retrieval?.metric('reranked_hit_at_k') ?? retrieval?.metric('embedding_hit_at_k');
    final mrr = retrieval?.metric('reranked_mrr') ?? retrieval?.metric('embedding_mrr');
    final ndcg = retrieval?.metric('reranked_ndcg_at_k') ?? retrieval?.metric('embedding_ndcg_at_k');
    final retrievalEvaluated = hit != null || mrr != null || ndcg != null;

    return Column(
      key: const Key('eval-retrieval-section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _ReportSectionHeading(
          number: 3,
          title: 'Retrieval Evaluation',
          subtitle: 'Did the chatbot find the right handbook or charter pages for the test questions, embedding-only vs. reranked?',
          sectionKey: Key('eval-section-3-retrieval'),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _RetrievalOverviewPanel(
                retrieval: retrieval,
                embedding: embedding,
                hit: hit,
                mrr: mrr,
                ndcg: ndcg,
                evaluated: retrievalEvaluated,
              ),
              const SizedBox(height: 16),
              EvalComparatorTable(
                title: 'Retrieval comparator',
                subtitle: 'Same 12 labeled queries, same isolated evaluation corpus. Bars are the metric values (0-1).',
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
                  EvalBarEntry(label: 'Hit@K\n(embed)', value: reranker?.metric('embedding_hit_at_k'), color: DesignTokens.maroonSoft),
                  EvalBarEntry(label: 'Hit@K\n(reranked)', value: reranker?.metric('reranked_hit_at_k'), color: DesignTokens.maroon),
                  EvalBarEntry(label: 'MRR\n(embed)', value: reranker?.metric('embedding_mrr'), color: DesignTokens.maroonSoft),
                  EvalBarEntry(label: 'MRR\n(reranked)', value: reranker?.metric('reranked_mrr'), color: DesignTokens.maroon),
                  EvalBarEntry(label: 'nDCG@K\n(embed)', value: reranker?.metric('embedding_ndcg_at_k'), color: DesignTokens.maroonSoft),
                  EvalBarEntry(label: 'nDCG@K\n(reranked)', value: reranker?.metric('reranked_ndcg_at_k'), color: DesignTokens.maroon),
                ],
                maxY: 1.0,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

String _percentLabel(double? value) {
  if (value == null) return '—';
  return '${(value * 100).toStringAsFixed(2)}%';
}

class _AtAGlanceRow extends StatelessWidget {
  const _AtAGlanceRow({
    required this.retrievalHit,
    required this.classificationAccuracy,
    required this.answersScored,
    this.answerCorrectness,
  });

  final double? retrievalHit;
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
                : 'Found a relevant page in the top 5',
          ),
          _glanceCard(
            color: DesignTokens.maroon,
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
            title: 'Retrieval Metrics',
            titleKey: const Key('eval-retrieval-overview-title'),
            statusKey: const Key('eval-retrieval-overview-status'),
            status: evaluated ? 'evaluated' : 'pending',
            subtitle: 'Did the chatbot find the right handbook or charter pages for the test questions?',
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
          'Hit = a relevant page was in the top 5. Embedding-only vs reranked use the same 12 labeled questions.',
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
  const _PendingCallout({super.key, required this.title, required this.body});

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

// --- shared lookup -----------------------------------------------------------

EvaluationComponentResult? _byName(List<EvaluationComponentResult> components, String name) {
  for (final c in components) {
    if (c.component == name) return c;
  }
  return null;
}

/// Shared loading/error/empty gate for the two Stage 3.2B-3.6 AI-judge
/// sections (QA Evaluation, Citation and Grounding Evaluation) -- both
/// read the same `QaCitationJudgingOverview` object and must degrade
/// identically and independently of each other.
Widget _qaJudgingGate({
  required QaCitationJudgingOverview? overview,
  required bool loading,
  required String? error,
  required VoidCallback onRetry,
  required Key loadingKey,
  required Key errorKey,
  required Key retryKey,
  required Key emptyKey,
  required String emptyBody,
  required Widget Function(QaCitationJudgingOverview data) builder,
}) {
  if (loading && overview == null && error == null) {
    return Padding(
      key: loadingKey,
      padding: const EdgeInsets.all(20),
      child: const Center(child: CircularProgressIndicator()),
    );
  }
  if (error != null && overview == null) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        EvalNotice(message: error, key: errorKey),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          key: retryKey,
          onPressed: onRetry,
          icon: const Icon(Icons.refresh_rounded, size: 18),
          label: const Text('Retry'),
        ),
      ],
    );
  }
  final data = overview;
  if (data == null || !data.available) {
    return _PendingCallout(
      key: emptyKey,
      title: 'QA and citation judging results are not available',
      body: emptyBody,
    );
  }
  return builder(data);
}

/// Section 4: "QA Evaluation". Two methodologically distinct measurements,
/// clearly labeled apart: the human-graded 0-1 RAG overview
/// ([_AnswerGenerationOverviewSection]) and the Stage 3.2B-3.6 dual-AI,
/// 0-4-scale QA judging below it -- never blended into one number.
class _QaEvaluationSection extends StatelessWidget {
  const _QaEvaluationSection({
    required this.components,
    required this.overview,
    required this.loading,
    required this.error,
    required this.onRetry,
  });

  final List<EvaluationComponentResult> components;
  final QaCitationJudgingOverview? overview;
  final bool loading;
  final String? error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('eval-qa-section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _ReportSectionHeading(
          number: 4,
          title: 'QA Evaluation',
          subtitle: 'Human-graded live chatbot answers, plus automated correctness/completeness/relevance/faithfulness scoring.',
          sectionKey: Key('eval-section-4-qa'),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _AnswerGenerationOverviewSection(components: components),
              const SizedBox(height: 24),
              const Divider(),
              const SizedBox(height: 16),
              _qaJudgingGate(
                overview: overview,
                loading: loading,
                error: error,
                onRetry: onRetry,
                loadingKey: const Key('eval-qa-judging-loading'),
                errorKey: const Key('eval-qa-judging-error'),
                retryKey: const Key('eval-qa-judging-retry'),
                emptyKey: const Key('eval-qa-judging-empty'),
                emptyBody:
                    'The Stage 3.2B-3.6 QA judging artifacts have not been produced yet, or one of them is currently unreadable. This does not mean the chatbot failed -- these results simply have not been computed.',
                builder: (data) => Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _OverviewSectionHeader(
                      title: 'QA Evaluation',
                      titleKey: const Key('eval-qa-grounding-qa-title'),
                      status: 'evaluated',
                      subtitle:
                          '${data.qaJudgedCount ?? 0} fully judged answerable cases · ${data.ieTotalCount ?? 0} insufficient-evidence cases'
                          '${(data.fallbackCount ?? 0) > 0 ? ' · ${data.fallbackCount} generation fallback excluded from genuine-output scoring' : ''}',
                    ),
                    const SizedBox(height: 14),
                    LayoutBuilder(
                      builder: (context, constraints) {
                        final columns = constraints.maxWidth >= 900 ? 5 : constraints.maxWidth >= 560 ? 3 : 1;
                        const gap = 12.0;
                        final width = constraints.maxWidth;
                        final cardWidth = columns == 1 ? width : (width - gap * (columns - 1)) / columns;
                        final cards = [
                          ('Correctness', data.qaCorrectness, 'eval-qa-card-correctness'),
                          ('Completeness', data.qaCompleteness, 'eval-qa-card-completeness'),
                          ('Relevance', data.qaRelevance, 'eval-qa-card-relevance'),
                          ('Faithfulness', data.qaFaithfulness, 'eval-qa-card-faithfulness'),
                          ('Overall', data.qaOverall, 'eval-qa-card-overall'),
                        ];
                        return Wrap(
                          spacing: gap,
                          runSpacing: gap,
                          children: [
                            for (final card in cards)
                              SizedBox(
                                width: cardWidth,
                                child: _ScaleMetricCard(
                                  cardKey: Key(card.$3),
                                  title: card.$1,
                                  value: card.$2,
                                  scaleMax: 4,
                                ),
                              ),
                          ],
                        );
                      },
                    ),
                    const SizedBox(height: 12),
                    if (data.qaJudgeDisagreementRate != null)
                      Text(
                        key: const Key('eval-qa-disagreement'),
                        'Judge disagreement: ${data.qaJudgeDisagreementRate!.numerator}/${data.qaJudgeDisagreementRate!.denominator} cases '
                        '(${((data.qaJudgeDisagreementRate!.value ?? 0) * 100).toStringAsFixed(1)}%) had at least one dimension where the two judges scored differently.',
                        style: const TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.4),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Section 5: "Citation and Grounding Evaluation". Stage 3.2B-3.6
/// claim-level citation metrics plus the Stage 3.6 citation-validity
/// correction -- kept deliberately separate from "capture coverage"
/// (whether any citation was shown at all), which is a different
/// measurement (see the coverage note rendered below).
class _CitationGroundingSection extends StatelessWidget {
  const _CitationGroundingSection({
    required this.overview,
    required this.loading,
    required this.error,
    required this.onRetry,
  });

  final QaCitationJudgingOverview? overview;
  final bool loading;
  final String? error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('eval-citation-section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _ReportSectionHeading(
          number: 5,
          title: 'Citation and Grounding Evaluation',
          subtitle: 'Citation precision, completeness, claim support, and the Stage 3.6-corrected citation validity.',
          sectionKey: Key('eval-section-5-citation'),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
          child: _qaJudgingGate(
            overview: overview,
            loading: loading,
            error: error,
            onRetry: onRetry,
            loadingKey: const Key('eval-citation-judging-loading'),
            errorKey: const Key('eval-citation-judging-error'),
            retryKey: const Key('eval-citation-judging-retry'),
            emptyKey: const Key('eval-citation-judging-empty'),
            emptyBody:
                'The Stage 3.2B-3.6 citation judging artifacts have not been produced yet, or one of them is currently unreadable. This does not mean the chatbot failed -- these results simply have not been computed.',
            builder: (data) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _OverviewSectionHeader(
                  title: 'Citation Evaluation',
                  titleKey: const Key('eval-qa-grounding-citation-title'),
                  status: 'evaluated',
                  subtitle:
                      '${data.citationJudgedCaseCount ?? 0} fully judged cases · ${data.citationJudgingFailedPartialCount ?? 0} partial judging failure(s)',
                ),
                const SizedBox(height: 14),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final columns = constraints.maxWidth >= 900 ? 5 : constraints.maxWidth >= 560 ? 3 : 1;
                    const gap = 12.0;
                    final width = constraints.maxWidth;
                    final cardWidth = columns == 1 ? width : (width - gap * (columns - 1)) / columns;
                    final cards = [
                      ('Precision', data.citationPrecision, 'eval-citation-card-precision'),
                      ('Completeness', data.citationCompleteness, 'eval-citation-card-completeness'),
                      ('Claim Support Rate', data.claimSupportRate, 'eval-citation-card-support'),
                      ('Unsupported Claim Rate', data.unsupportedClaimRate, 'eval-citation-card-unsupported'),
                      ('Citation Validity (corrected)', data.citationValidityCorrected, 'eval-citation-card-validity'),
                    ];
                    return Wrap(
                      spacing: gap,
                      runSpacing: gap,
                      children: [
                        for (final card in cards)
                          SizedBox(
                            width: cardWidth,
                            child: _FractionMetricCard(
                              cardKey: Key(card.$3),
                              title: card.$1,
                              fraction: card.$2,
                              highlight: card.$3 == 'eval-citation-card-validity',
                            ),
                          ),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 16),
                Container(
                  key: const Key('eval-citation-validity-correction-note'),
                  width: double.infinity,
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: DesignTokens.maroonWash,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: DesignTokens.maroon.withValues(alpha: 0.28),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Citation validity: original vs. corrected',
                        style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13, color: DesignTokens.ink),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'Originally computed as ${data.citationValidityOriginalDefective?.numerator ?? 0}/'
                        '${data.citationValidityOriginalDefective?.denominator ?? 0} '
                        '(${(((data.citationValidityOriginalDefective?.value ?? 0)) * 100).toStringAsFixed(0)}%) due to a confirmed defect that compared two unrelated identifier systems. '
                        'Fixed and independently verified: the corrected value shown above is '
                        '${data.citationValidityCorrected?.numerator ?? 0}/${data.citationValidityCorrected?.denominator ?? 0} '
                        '(${(((data.citationValidityCorrected?.value ?? 0)) * 100).toStringAsFixed(0)}%). The other four citation metrics were confirmed unchanged by this fix.',
                        style: const TextStyle(color: DesignTokens.ink, fontSize: 12, height: 1.4),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                Container(
                  key: const Key('eval-citation-vs-coverage-note'),
                  width: double.infinity,
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFEF2F2),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: const Color(0xFFFECACA)),
                  ),
                  child: Text(
                    'Do not confuse citation validity (${((data.citationValidityCorrected?.value ?? 0) * 100).toStringAsFixed(0)}%, "was the citation ID real?") with claim support rate '
                    '(${((data.claimSupportRate?.value ?? 0) * 100).toStringAsFixed(1)}%, "was the claim actually backed by what was cited?"). '
                    'Separately, Stage 3.4 capture coverage showed ${data.captureCasesWithCitations ?? 0}/${data.captureTotalCases ?? 0} cases had any displayed citation at all -- that is a different measurement again (whether a citation was shown), not citation correctness.',
                    style: const TextStyle(color: Color(0xFF991B1B), fontSize: 12, height: 1.4),
                  ),
                ),
                const SizedBox(height: 16),
                if (data.limitations.isNotEmpty)
                  Container(
                    key: const Key('eval-qa-grounding-limitations'),
                    width: double.infinity,
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF8FAFC),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: DesignTokens.border),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Known limitations',
                          style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13, color: DesignTokens.ink),
                        ),
                        const SizedBox(height: 8),
                        for (final note in data.limitations) ...[
                          Text('•  $note', style: const TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.4)),
                          const SizedBox(height: 6),
                        ],
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _ScaleMetricCard extends StatelessWidget {
  const _ScaleMetricCard({
    required this.cardKey,
    required this.title,
    required this.value,
    required this.scaleMax,
  });

  final Key cardKey;
  final String title;
  final double? value;
  final double scaleMax;

  @override
  Widget build(BuildContext context) {
    final evaluated = value != null;
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
            evaluated ? '${value!.toStringAsFixed(2)} / ${scaleMax.toStringAsFixed(0)}' : '—',
            style: TextStyle(
              color: evaluated ? DesignTokens.ink : const Color(0xFF94A3B8),
              fontSize: 20,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class _FractionMetricCard extends StatelessWidget {
  const _FractionMetricCard({
    required this.cardKey,
    required this.title,
    required this.fraction,
    this.highlight = false,
  });

  final Key cardKey;
  final String title;
  final EvalFraction? fraction;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final value = fraction?.value;
    final evaluated = value != null;
    return Container(
      key: cardKey,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: !evaluated
            ? const Color(0xFFF8FAFC)
            : (highlight ? const Color(0xFFF0FDF4) : Colors.white),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: !evaluated
              ? const Color(0xFFE2E8F0)
              : (highlight ? const Color(0xFFBBF7D0) : DesignTokens.border),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(color: DesignTokens.muted, fontSize: 11, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          Text(
            evaluated ? '${(value * 100).toStringAsFixed(1)}%' : '—',
            style: TextStyle(
              color: evaluated ? DesignTokens.ink : const Color(0xFF94A3B8),
              fontSize: 20,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            fraction == null ? 'Not computed' : '${fraction!.numerator}/${fraction!.denominator}',
            style: const TextStyle(color: DesignTokens.muted, fontSize: 11),
          ),
        ],
      ),
    );
  }
}

// --- Methodology ---------------------------------------------------------

/// One methodology topic: a plain-language explanation plus the exact
/// backend file(s)/line(s) it is drawn from, so every claim here is
/// traceable to the real implementation rather than a generic description.
class _MethodologyBlock {
  const _MethodologyBlock({required this.title, required this.body, required this.citations});

  final String title;
  final String body;
  final List<String> citations;
}

const List<_MethodologyBlock> _kMethodologyBlocks = [
  _MethodologyBlock(
    title: 'Dataset and case selection',
    body:
        'Cases belong to experiment family "qa_citation_v1" and fall into exactly two types: '
        'labeled_student_support (ordinary answerable questions) and insufficient_evidence '
        '(deliberately unanswerable from the corpus). Only student-facing cases are ever loaded as '
        'live evaluation cases -- faculty-as-audience cases are rejected, and example/placeholder '
        'artifacts marked example_only or not_an_evaluation_result are never treated as real cases.',
    citations: [
      'backend/app/services/evaluation/qa_citation_dataset.py:6-10 (module docstring)',
      'backend/app/services/evaluation/qa_citation_dataset.py:31 (EXPERIMENT_FAMILY)',
      'backend/app/services/evaluation/qa_citation_dataset.py:35-39 (CASE_TYPES)',
    ],
  ),
  _MethodologyBlock(
    title: 'Dataset and corpus version/digests',
    body:
        'All QA/citation runs score against one locked, frozen 691-chunk Chroma extract, identified '
        'by two digests (an identity digest and a metadata-text digest) -- never the dataset JSON\'s '
        'own sha256, which is a separate, unrelated hash. Every capture and judging run verifies its '
        'corpus against these two digests before scoring and records the result; the accepted run used '
        'dataset version 2026-11-09-v1.1.',
    citations: [
      'backend/app/services/evaluation/qa_citation_dataset.py:12-14 (module docstring)',
      'backend/app/services/evaluation/qa_citation_dataset.py:51-58 (LOCKED_CORPUS_*, LOCKED_IDENTITY_DIGEST, LOCKED_METADATA_TEXT_DIGEST)',
      'backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json (the locked extract artifact)',
    ],
  ),
  _MethodologyBlock(
    title: 'Classification evaluation method and metrics',
    body:
        'Classification (student-question category, handbook-chunk category) is scored with a pure, '
        'no-I/O multiclass one-vs-rest implementation: accuracy, macro/weighted precision, recall, and '
        'F1 per class. A class with a zero denominator (never predicted, or never actually present) '
        'reports 0.0 by explicit convention -- never a fabricated or omitted value.',
    citations: [
      'backend/app/services/evaluation/classification_metrics.py:1-5 (module docstring)',
      'backend/app/services/evaluation/classification_metrics.py:29-40 (ClassificationMetrics)',
      'backend/app/services/evaluation/classification_metrics.py:43-49 (_safe_divide)',
      'backend/app/services/evaluation/classification_metrics.py:52 (evaluate_classification)',
    ],
  ),
  _MethodologyBlock(
    title: 'Retrieval benchmark and ranking metrics',
    body:
        'Retrieval is scored with pure Hit@K, MRR, Precision@K, Recall@K, and nDCG@K functions that take '
        'already-retrieved ranked id lists plus labeled relevance judgments -- the exact same metric code '
        'scores both the embedding-only ranking and the post-reranking ranking, so the ablation comparison '
        'is an apples-to-apples use of one implementation. The 12 human-labeled questions are scored '
        'against the isolated 691-chunk evaluation Chroma index (source run 131ba7a4-...), never live '
        'student Chroma.',
    citations: [
      'backend/app/services/evaluation/retrieval_metrics.py:1-9 (module docstring)',
      'backend/app/services/evaluation/retrieval_metrics.py:41-49 (RetrievalMetrics)',
      'backend/app/services/evaluation/retrieval_metrics.py:52-60 (nDCG@K: DCG@K / IDCG@K)',
      'backend/app/services/evaluation/labeled_retrieval_overview.py:1-9 (module docstring)',
    ],
  ),
  _MethodologyBlock(
    title: 'Actual QA chatbot execution and dual-AI judging procedure',
    body:
        'Each case is a real, live chatbot answer capture (not a canned response). Before ordinary QA '
        'judging, a fail-closed eligibility check requires execution_status == "ok" AND '
        'is_genuine_model_output is True AND fallback_used is False AND a non-empty generated answer; '
        'any missing field excludes the case rather than assuming eligibility. Eligible cases are then '
        'judged by two independent AI judge calls (never a human rater). The combination rule is the '
        'same everywhere: both judges succeed -> judged; exactly one succeeds -> judging_failed_partial '
        '(no combined score; the surviving judge is kept for diagnostics only, never presented as the '
        'result); both fail -> judging_failed_total. There are no automatic retries.',
    citations: [
      'backend/app/services/evaluation/qa_citation_eligibility.py:101-171 (classify_eligibility)',
      'backend/app/services/evaluation/qa_citation_metrics.py:119-159 (JUDGING_STATUS_* definitions)',
      'backend/app/services/evaluation/qa_citation_judging.py:94-108 (JudgeSlotOutcome, JudgingOutcome)',
    ],
  ),
  _MethodologyBlock(
    title: 'QA scoring rubric and aggregation',
    body:
        'Every judged case is scored on four criteria -- correctness, completeness, relevance, '
        'faithfulness -- each an integer 0-4. The reported value per criterion is the arithmetic mean '
        'of the two judges\' scores (never the maximum, never a single judge standing in); "Overall" is '
        'the mean of the four criteria means. A case is flagged as a judge disagreement when the two '
        'judges differ by 1 or more on any single criterion. Faithfulness is judged against retrieved/'
        'displayed evidence, not similarity to a reference answer.',
    citations: [
      'backend/app/services/evaluation/qa_citation_metrics.py:66-69 (QA_CRITERIA, QA_DISAGREEMENT_THRESHOLD)',
      'backend/app/services/evaluation/qa_citation_metrics.py:316-352 (aggregate_dual_ai_qa_scores)',
      'backend/app/services/evaluation/qa_citation_run_report.py:229-314 (_qa_dimension_means, _qa_disagreement, _build_qa_aggregation)',
    ],
  ),
  _MethodologyBlock(
    title: 'Citation claim extraction and dual-judge evaluation',
    body:
        'Citation-claim judging is a separate two-judge call from QA scoring, with its own failure '
        'domain, so a malformed QA response never voids an otherwise-good claim extraction or vice '
        'versa. Each judge independently extracts the answer\'s factual claims, marks which require a '
        'citation, and assesses each citation-required claim as supported / unsupported / '
        'not_assessable against the case\'s own displayed citation ids -- never an id the judge invents. '
        'Both judges\' claim sets are preserved and scored independently; the run-level aggregation sums '
        'counts across every (case, judge-slot) data point before computing a fraction, rather than '
        'averaging two already-computed per-case fractions.',
    citations: [
      'backend/app/services/evaluation/qa_citation_claim_judging.py:1-50 (module docstring)',
      'backend/app/services/evaluation/qa_citation_metrics.py:6-53 (claim status definitions)',
    ],
  ),
  _MethodologyBlock(
    title: 'Citation validity verification and the Stage 3.6 correction',
    body:
        'citation_precision is the share of unique displayed citation ids that back at least one claim. '
        'citation_completeness is the share of citation-required claims that have at least one '
        'supporting displayed id. claim_support_rate / unsupported_claim_rate are the shares of '
        'citation-required claims marked supported / unsupported. citation_validity is the share of '
        'unique displayed citation ids that resolve against the locked 691-chunk extract\'s own chunk-id '
        'index. A defect found and fixed in Stage 3.6: the original resolver additionally cross-checked '
        'an unrelated application-level Document-table UUID against the extract\'s own document id -- two '
        'unrelated identifier namespaces -- which produced a spurious mismatch for every real citation '
        '(0/86). The fix removed that cross-check; resolution now uses only the locked extract\'s own '
        'chunk-id lookup. The corrected value (86/86, 100%) was independently verified against the other '
        'four citation metrics, confirmed byte-identical before and after the fix.',
    citations: [
      'backend/app/services/evaluation/qa_citation_metrics.py:407-437 (compute_citation_metrics)',
      'backend/app/services/evaluation/qa_citation_claim_judging.py:353-399 (resolve_citation_validity, Stage 3.6 fix)',
      'backend/benchmarks/evaluation/qa_citation_runs/qacj_citation_validity_correction_20261110T112506Z/citation_validity_correction.json',
    ],
  ),
  _MethodologyBlock(
    title: 'Treatment of insufficient evidence, fallback outputs, and partial failures',
    body:
        'A generation fallback (a safe canned response substituted for a real model answer) is excluded '
        'from genuine-output scoring entirely -- it is never scored as if it were a real answer. '
        'insufficient_evidence cases (deliberately unanswerable from the corpus) are scored on a '
        'separate binary rubric -- correctly_declined vs. unsupported_claim_detected -- not the 0-4 QA '
        'scale, since "did the chatbot correctly decline" is a different question from "how good was '
        'the answer." Eligibility exclusions (missing fields, no result, fallback-not-genuine, refusal '
        'not QA-scored, empty answer) are recorded by reason, never silently dropped. A single '
        'surviving judge in a judging_failed_partial case is kept only for diagnostics, never reported '
        'as a result.',
    citations: [
      'backend/app/services/evaluation/qa_citation_eligibility.py:101-171 (exclusion reasons)',
      'backend/app/services/evaluation/qa_citation_insufficient_evidence.py (InsufficientEvidenceJudgeAdapter)',
      'backend/app/services/evaluation/qa_citation_metrics.py:149-158 (JUDGING_STATUS_FAILED_PARTIAL / _TOTAL)',
    ],
  ),
  _MethodologyBlock(
    title: 'How run-level metrics are aggregated',
    body:
        'run_qa_citation_judging() orchestrates all three rubrics (QA, insufficient-evidence, citation-'
        'claims) for one capture run in a single pass. Classification, retrieval, and QA/citation each '
        'have their own independent aggregation; this report never recombines numbers across those three '
        'systems into one blended score. Denominators are always shown alongside every fraction (e.g. '
        '78/86) so a percentage is never presented without the counts it came from.',
    citations: [
      'backend/app/services/evaluation/qa_citation_run_report.py:410 (run_qa_citation_judging)',
      'backend/app/services/evaluation/qa_citation_metrics.py:182-206 (FractionMetric.from_counts)',
    ],
  ),
];

/// Section 6: "Evaluation Methodology and Computation Process". Static,
/// hand-written content sourced directly from the backend code and
/// artifact filenames cited inline -- not a generic description. No
/// video reference was available to this implementation; this section
/// follows the written structure of the request instead.
class _MethodologySection extends StatelessWidget {
  const _MethodologySection();

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('eval-methodology-section'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _ReportSectionHeading(
          number: 6,
          title: 'Evaluation Methodology and Computation Process',
          subtitle: 'How each result above was produced, with the exact backend file/line it comes from.',
          sectionKey: Key('eval-section-6-methodology'),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                key: const Key('eval-methodology-automated-disclosure'),
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFFF8FAFC),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: DesignTokens.border),
                ),
                child: const Text(
                  'QA and citation scores were produced through independent automated '
                  'model-based assessments. These results are automated evaluations and '
                  'should not be interpreted as human ratings.',
                  style: TextStyle(color: DesignTokens.ink, fontSize: 13, height: 1.45, fontWeight: FontWeight.w600),
                ),
              ),
              const SizedBox(height: 16),
              for (var i = 0; i < _kMethodologyBlocks.length; i++) ...[
                if (i > 0) const SizedBox(height: 10),
                _MethodologyPanel(block: _kMethodologyBlocks[i], initiallyExpanded: i == 0),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _MethodologyPanel extends StatelessWidget {
  const _MethodologyPanel({required this.block, required this.initiallyExpanded});

  final _MethodologyBlock block;
  final bool initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: Container(
        key: Key('eval-methodology-${block.title}'),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: DesignTokens.border),
        ),
        child: ExpansionTile(
          initiallyExpanded: initiallyExpanded,
          tilePadding: const EdgeInsets.symmetric(horizontal: 16),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          title: Text(
            block.title,
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14, color: DesignTokens.ink),
          ),
          children: [
            Text(block.body, style: const TextStyle(color: DesignTokens.ink, fontSize: 13, height: 1.5)),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                for (final citation in block.citations)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                    decoration: BoxDecoration(color: DesignTokens.bgGrey, borderRadius: BorderRadius.circular(6)),
                    child: Text(
                      citation,
                      style: const TextStyle(fontFamily: 'monospace', fontSize: 11, color: DesignTokens.muted),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
