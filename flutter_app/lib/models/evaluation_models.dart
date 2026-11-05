/// Data models for the Model Evaluation System admin dashboard.
///
/// These mirror the backend's Pydantic response shapes exactly (see
/// backend/app/models/schemas.py's Evaluation* schemas) -- field names,
/// nullability, and "metric_value is null means not computed" semantics
/// are preserved as-is, never coerced to a fabricated 0 here.
library;

import 'dart:convert';

class EvaluationModelInfo {
  const EvaluationModelInfo({
    required this.component,
    required this.modelName,
    this.sharesModelWith,
    this.allowLlmFallback,
  });

  final String component;
  final String modelName;
  final String? sharesModelWith;
  final bool? allowLlmFallback;

  factory EvaluationModelInfo.fromJson(Map<String, dynamic> json) {
    return EvaluationModelInfo(
      component: json['component']?.toString() ?? '',
      modelName: json['model_name']?.toString() ?? '',
      sharesModelWith: json['shares_model_with']?.toString(),
      allowLlmFallback: json['allow_llm_fallback'] as bool?,
    );
  }
}

class EvaluationMetric {
  const EvaluationMetric({
    required this.metricName,
    this.metricValue,
    this.extra,
  });

  final String metricName;
  /// Null means this metric genuinely was not computed -- never a
  /// fabricated 0.0. UI must distinguish "unavailable" from "zero".
  final double? metricValue;
  final dynamic extra;

  factory EvaluationMetric.fromJson(Map<String, dynamic> json) {
    final raw = json['metric_value'];
    return EvaluationMetric(
      metricName: json['metric_name']?.toString() ?? '',
      metricValue: raw == null ? null : (raw as num).toDouble(),
      extra: json['extra'],
    );
  }
}

class EvaluationComponentResult {
  const EvaluationComponentResult({
    required this.componentId,
    required this.component,
    required this.status,
    this.reason,
    this.note,
    required this.modelName,
    this.sharesModelWith,
    this.allowLlmFallback,
    required this.caseCount,
    required this.skippedUnlabeledCount,
    required this.hasConfusionMatrix,
    required this.metrics,
  });

  final String componentId;
  final String component;
  /// "evaluated" | "not_evaluable" | "failed"
  final String status;
  final String? reason;
  final String? note;
  final String modelName;
  final String? sharesModelWith;
  final bool? allowLlmFallback;
  final int caseCount;
  final int skippedUnlabeledCount;
  final bool hasConfusionMatrix;
  final List<EvaluationMetric> metrics;

  factory EvaluationComponentResult.fromJson(Map<String, dynamic> json) {
    final rawMetrics = (json['metrics'] as List?) ?? const [];
    return EvaluationComponentResult(
      componentId: json['component_id']?.toString() ?? '',
      component: json['component']?.toString() ?? '',
      status: json['status']?.toString() ?? 'not_evaluable',
      reason: json['reason']?.toString(),
      note: json['note']?.toString(),
      modelName: json['model_name']?.toString() ?? '',
      sharesModelWith: json['shares_model_with']?.toString(),
      allowLlmFallback: json['allow_llm_fallback'] as bool?,
      caseCount: (json['case_count'] as num?)?.toInt() ?? 0,
      skippedUnlabeledCount: (json['skipped_unlabeled_count'] as num?)?.toInt() ?? 0,
      hasConfusionMatrix: json['has_confusion_matrix'] == true,
      metrics: rawMetrics
          .whereType<Map>()
          .map((m) => EvaluationMetric.fromJson(Map<String, dynamic>.from(m)))
          .toList(),
    );
  }

  /// Null when the metric is not present at all, OR present with a null
  /// value -- both mean "unavailable". Use [hasMetric] to tell apart
  /// "never computed" from a genuine 0.0 if that distinction matters.
  double? metric(String name) {
    for (final m in metrics) {
      if (m.metricName == name) return m.metricValue;
    }
    return null;
  }

  /// True only when this metric was actually computed (value is non-null).
  bool hasMetric(String name) {
    for (final m in metrics) {
      if (m.metricName == name) return m.metricValue != null;
    }
    return false;
  }

  EvaluationMetric? metricRow(String name) {
    for (final m in metrics) {
      if (m.metricName == name) return m;
    }
    return null;
  }

  /// Rows from the backend `per_class_breakdown` extra payload. Empty when
  /// that metric was never persisted — never synthesized.
  List<ClassificationClassBreakdown> perClassBreakdown() {
    final extra = metricRow('per_class_breakdown')?.extra;
    final raw = extra is List
        ? extra
        : extra is String
            ? jsonDecode(extra)
            : null;
    if (raw is! List) return const [];
    final rows = <ClassificationClassBreakdown>[];
    for (final item in raw) {
      if (item is! Map) continue;
      final map = Map<String, dynamic>.from(item);
      rows.add(ClassificationClassBreakdown.fromJson(map));
    }
    return rows;
  }

  /// Human overlay per-question scores. Empty when the overlay did not
  /// include a `per_case_breakdown` extra — never synthesized here.
  List<HumanRagCaseScore> humanRagCases() {
    final extra = metricRow('per_case_breakdown')?.extra;
    final raw = extra is List
        ? extra
        : extra is String
            ? jsonDecode(extra)
            : null;
    if (raw is! List) return const [];
    final rows = <HumanRagCaseScore>[];
    for (final item in raw) {
      if (item is! Map) continue;
      rows.add(HumanRagCaseScore.fromJson(Map<String, dynamic>.from(item)));
    }
    return rows;
  }

  /// Isolated-corpus retrieval overlay rows. Empty when that extra is
  /// absent or is the human QA case list — never synthesized.
  List<RetrievalCaseScore> retrievalCases() {
    final extra = metricRow('per_case_breakdown')?.extra;
    final raw = extra is List
        ? extra
        : extra is String
            ? jsonDecode(extra)
            : null;
    if (raw is! List) return const [];
    final rows = <RetrievalCaseScore>[];
    for (final item in raw) {
      if (item is! Map) continue;
      final map = Map<String, dynamic>.from(item);
      if (!map.containsKey('embedding_hit') && !map.containsKey('reranked_hit')) {
        continue;
      }
      rows.add(RetrievalCaseScore.fromJson(map));
    }
    return rows;
  }
}

class RetrievalCaseScore {
  const RetrievalCaseScore({
    required this.caseId,
    required this.question,
    this.embeddingHit,
    this.rerankedHit,
  });

  final String caseId;
  final String question;
  final bool? embeddingHit;
  final bool? rerankedHit;

  factory RetrievalCaseScore.fromJson(Map<String, dynamic> json) {
    return RetrievalCaseScore(
      caseId: json['case_id']?.toString() ?? '',
      question: json['question']?.toString() ?? '',
      embeddingHit: json['embedding_hit'] as bool?,
      rerankedHit: json['reranked_hit'] as bool?,
    );
  }
}

class HumanRagCaseScore {
  const HumanRagCaseScore({
    required this.caseId,
    required this.question,
    required this.included,
    this.exclusionReason,
    this.note,
    this.correctness,
    this.faithfulness,
    this.relevance,
    this.citation,
  });

  final String caseId;
  final String question;
  final bool included;
  final String? exclusionReason;
  final String? note;
  final HumanRagDimensionScore? correctness;
  final HumanRagDimensionScore? faithfulness;
  final HumanRagDimensionScore? relevance;
  final HumanRagDimensionScore? citation;

  factory HumanRagCaseScore.fromJson(Map<String, dynamic> json) {
    return HumanRagCaseScore(
      caseId: json['case_id']?.toString() ?? '',
      question: json['question']?.toString() ?? '',
      included: json['included'] != false,
      exclusionReason: json['exclusion_reason']?.toString(),
      note: json['note']?.toString(),
      correctness: HumanRagDimensionScore.tryParse(json['correctness']),
      faithfulness: HumanRagDimensionScore.tryParse(json['faithfulness']),
      relevance: HumanRagDimensionScore.tryParse(json['relevance']),
      citation: HumanRagDimensionScore.tryParse(json['citation']),
    );
  }
}

class HumanRagDimensionScore {
  const HumanRagDimensionScore({required this.label, this.score});

  final String label;
  final double? score;

  static HumanRagDimensionScore? tryParse(dynamic raw) {
    if (raw is! Map) return null;
    final map = Map<String, dynamic>.from(raw);
    final label = map['label']?.toString() ?? '';
    if (label.isEmpty && map['score'] == null) return null;
    final value = map['score'];
    return HumanRagDimensionScore(
      label: label,
      score: value == null ? null : (value as num).toDouble(),
    );
  }
}

class ClassificationClassBreakdown {
  const ClassificationClassBreakdown({
    required this.label,
    required this.precision,
    required this.recall,
    required this.f1,
    required this.support,
  });

  final String label;
  final double? precision;
  final double? recall;
  final double? f1;
  final int? support;

  factory ClassificationClassBreakdown.fromJson(Map<String, dynamic> json) {
    double? asDouble(Object? value) => value is num ? value.toDouble() : null;
    int? asInt(Object? value) => value is num ? value.toInt() : null;
    return ClassificationClassBreakdown(
      label: json['label']?.toString() ?? '',
      precision: asDouble(json['precision']),
      recall: asDouble(json['recall']),
      f1: asDouble(json['f1']),
      support: asInt(json['support']),
    );
  }
}

class EvaluationRunSummary {
  const EvaluationRunSummary({
    required this.runId,
    required this.status,
    this.triggeredByUserId,
    required this.startedAt,
    this.completedAt,
    this.errorMessage,
  });

  final String runId;
  /// "running" | "completed" | "failed"
  final String status;
  final String? triggeredByUserId;
  final String startedAt;
  final String? completedAt;
  final String? errorMessage;

  factory EvaluationRunSummary.fromJson(Map<String, dynamic> json) {
    return EvaluationRunSummary(
      runId: json['run_id']?.toString() ?? '',
      status: json['status']?.toString() ?? 'running',
      triggeredByUserId: json['triggered_by_user_id']?.toString(),
      startedAt: json['started_at']?.toString() ?? '',
      completedAt: json['completed_at']?.toString(),
      errorMessage: json['error_message']?.toString(),
    );
  }
}

class EvaluationRunDetail {
  const EvaluationRunDetail({
    required this.summary,
    required this.config,
    required this.components,
  });

  final EvaluationRunSummary summary;
  final Map<String, dynamic> config;
  final List<EvaluationComponentResult> components;

  factory EvaluationRunDetail.fromJson(Map<String, dynamic> json) {
    final rawComponents = (json['components'] as List?) ?? const [];
    return EvaluationRunDetail(
      summary: EvaluationRunSummary.fromJson(json),
      config: json['config'] is Map ? Map<String, dynamic>.from(json['config'] as Map) : const {},
      components: rawComponents
          .whereType<Map>()
          .map((c) => EvaluationComponentResult.fromJson(Map<String, dynamic>.from(c)))
          .toList(),
    );
  }
}

class EvaluationRunHistoryPage {
  const EvaluationRunHistoryPage({
    required this.runs,
    required this.total,
    required this.limit,
    required this.offset,
  });

  final List<EvaluationRunSummary> runs;
  final int total;
  final int limit;
  final int offset;

  factory EvaluationRunHistoryPage.fromJson(Map<String, dynamic> json) {
    final rawRuns = (json['runs'] as List?) ?? const [];
    return EvaluationRunHistoryPage(
      runs: rawRuns
          .whereType<Map>()
          .map((r) => EvaluationRunSummary.fromJson(Map<String, dynamic>.from(r)))
          .toList(),
      total: (json['total'] as num?)?.toInt() ?? 0,
      limit: (json['limit'] as num?)?.toInt() ?? 0,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
    );
  }
}

class EvaluationSummary {
  const EvaluationSummary({this.latestRun, required this.components});

  final EvaluationRunSummary? latestRun;
  final List<EvaluationComponentResult> components;

  factory EvaluationSummary.fromJson(Map<String, dynamic> json) {
    final rawLatest = json['latest_run'];
    final rawComponents = (json['components'] as List?) ?? const [];
    return EvaluationSummary(
      latestRun: rawLatest is Map
          ? EvaluationRunSummary.fromJson(Map<String, dynamic>.from(rawLatest))
          : null,
      components: rawComponents
          .whereType<Map>()
          .map((c) => EvaluationComponentResult.fromJson(Map<String, dynamic>.from(c)))
          .toList(),
    );
  }
}

class EvaluationConfusionMatrix {
  const EvaluationConfusionMatrix({
    required this.component,
    required this.labels,
    required this.matrix,
    required this.caseCount,
  });

  final String component;
  final List<String> labels;
  final List<List<int>> matrix;
  final int caseCount;

  factory EvaluationConfusionMatrix.fromJson(Map<String, dynamic> json) {
    final rawLabels = (json['labels'] as List?) ?? const [];
    final rawMatrix = (json['matrix'] as List?) ?? const [];
    return EvaluationConfusionMatrix(
      component: json['component']?.toString() ?? '',
      labels: rawLabels.map((e) => e.toString()).toList(),
      matrix: rawMatrix
          .whereType<List>()
          .map((row) => row.map((v) => (v as num).toInt()).toList())
          .toList(),
      caseCount: (json['case_count'] as num?)?.toInt() ?? 0,
    );
  }
}

class EvaluationCaseResultItem {
  const EvaluationCaseResultItem({
    required this.caseId,
    this.predicted,
    this.expected,
    this.correct,
    this.latencyMs,
  });

  final String caseId;
  final String? predicted;
  final String? expected;
  final bool? correct;
  final double? latencyMs;

  factory EvaluationCaseResultItem.fromJson(Map<String, dynamic> json) {
    final rawLatency = json['latency_ms'];
    return EvaluationCaseResultItem(
      caseId: json['case_id']?.toString() ?? '',
      predicted: json['predicted']?.toString(),
      expected: json['expected']?.toString(),
      correct: json['correct'] as bool?,
      latencyMs: rawLatency == null ? null : (rawLatency as num).toDouble(),
    );
  }
}

class EvaluationCaseResultsPage {
  const EvaluationCaseResultsPage({
    required this.component,
    required this.caseResults,
    required this.total,
    required this.limit,
    required this.offset,
  });

  final String component;
  final List<EvaluationCaseResultItem> caseResults;
  final int total;
  final int limit;
  final int offset;

  factory EvaluationCaseResultsPage.fromJson(Map<String, dynamic> json) {
    final rawCases = (json['case_results'] as List?) ?? const [];
    return EvaluationCaseResultsPage(
      component: json['component']?.toString() ?? '',
      caseResults: rawCases
          .whereType<Map>()
          .map((c) => EvaluationCaseResultItem.fromJson(Map<String, dynamic>.from(c)))
          .toList(),
      total: (json['total'] as num?)?.toInt() ?? 0,
      limit: (json['limit'] as num?)?.toInt() ?? 0,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
    );
  }
}
