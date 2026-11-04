/// Structured classification report for Admin Model Evaluation.
///
/// Presentational only: every number comes from [EvaluationComponentResult]
/// / [EvaluationConfusionMatrix] already fetched for the selected run.
library;

import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../models/evaluation_models.dart';
import 'admin_model_evaluation_charts.dart';

const String kIndependentAiAnnotationDatasetVersion =
    '2026-11-04-v2-independent-ai-annotation-dual-agreement';

EvaluationComponentResult? classificationByName(
  List<EvaluationComponentResult> components,
  String name,
) {
  for (final c in components) {
    if (c.component == name) return c;
  }
  return null;
}

String formatAccuracyPercent(double? value) {
  if (value == null) return '—';
  return '${(value * 100).toStringAsFixed(2)}%';
}

String formatMetricScore(double? value) {
  if (value == null) return '—';
  return value.toStringAsFixed(4);
}

class ClassificationOverviewSection extends StatelessWidget {
  const ClassificationOverviewSection({
    super.key,
    required this.components,
    this.config = const {},
    this.title = 'Classification Overview',
  });

  final List<EvaluationComponentResult> components;
  final Map<String, dynamic> config;
  final String title;

  @override
  Widget build(BuildContext context) {
    final question = classificationByName(components, 'classify_question');
    final chunkOn = classificationByName(components, 'classify_chunk(allow_llm=True)');
    final chunkOff = classificationByName(components, 'classify_chunk(allow_llm=False)');
    final versions = config['dataset_versions'];
    final classificationVersion =
        versions is Map ? versions['classification']?.toString() : null;
    final showCensus = classificationVersion == kIndependentAiAnnotationDatasetVersion;
    final autoAccepted = (question?.status == 'evaluated' ? question!.caseCount : 0) +
        (chunkOn?.status == 'evaluated'
            ? chunkOn!.caseCount
            : chunkOff?.status == 'evaluated'
                ? chunkOff!.caseCount
                : 0);

    final questionEvaluated = question?.status == 'evaluated';
    final chunkPrimary = chunkOn?.status == 'evaluated' ? chunkOn : chunkOff;
    final bothChunksEvaluated =
        chunkOn?.status == 'evaluated' && chunkOff?.status == 'evaluated';
    final chunkScoresMatch = bothChunksEvaluated &&
        chunkOn!.metric('accuracy') == chunkOff!.metric('accuracy') &&
        chunkOn.metric('macro_f1') == chunkOff.metric('macro_f1');

    final scoreCards = <(String, String, String?)>[
      _overviewCard('Student questions', question),
    ];
    if (chunkPrimary?.status == 'evaluated') {
      scoreCards.add(_overviewCard('Document chunks', chunkPrimary));
    } else if (chunkOn != null || chunkOff != null) {
      scoreCards.add(_overviewCard('Document chunks', chunkPrimary ?? chunkOn ?? chunkOff));
    }
    if (bothChunksEvaluated && !chunkScoresMatch) {
      scoreCards.add(_overviewCard('Document chunks (no LLM)', chunkOff));
    }

    final evaluated = questionEvaluated || chunkPrimary?.status == 'evaluated';

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
          Wrap(
            spacing: 10,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                title,
                key: const Key('eval-classification-overview-title'),
                style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900, color: DesignTokens.ink),
              ),
              _statusPill(evaluated),
            ],
          ),
          const SizedBox(height: 6),
          const Text(
            'Did the system assign the right category to student questions and handbook passages?',
            style: TextStyle(color: DesignTokens.muted, fontSize: 13, height: 1.4),
          ),
          const SizedBox(height: 16),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 640 ? (scoreCards.length > 1 ? 2 : 1) : 1;
              return _OverviewCardGrid(columns: columns, cards: scoreCards);
            },
          ),
          if (chunkScoresMatch) ...[
            const SizedBox(height: 10),
            const Text(
              'Chunk tagging scored the same with the LLM fallback on or off, so only one result is shown.',
              style: TextStyle(color: DesignTokens.muted, fontSize: 12),
            ),
          ],
          const SizedBox(height: 16),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: DesignTokens.bgGrey,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Wrap(
              spacing: 22,
              runSpacing: 10,
              children: [
                _censusChip('Scored in this run', autoAccepted > 0 ? '$autoAccepted' : '—'),
                if (showCensus) ...[
                  _censusChip('Labeling pool', '96'),
                  _censusChip('Held out', '31'),
                ] else
                  _censusChip('Held out', '—'),
              ],
            ),
          ),
          if (showCensus) ...[
            const SizedBox(height: 8),
            const Text(
              'Held-out cases were disagreements, out-of-scope, or missing enough evidence to label.',
              style: TextStyle(color: DesignTokens.muted, fontSize: 12, height: 1.35),
            ),
          ],
          if (!questionEvaluated && (question?.reason != null)) ...[
            const SizedBox(height: 8),
            Text(question!.reason!, style: const TextStyle(color: DesignTokens.muted, fontSize: 12)),
          ],
        ],
      ),
    );
  }

  Widget _statusPill(bool evaluated) {
    final bg = evaluated ? const Color(0xFFDCFCE7) : const Color(0xFFF3F4F6);
    final fg = evaluated ? const Color(0xFF166534) : const Color(0xFF4B5563);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
      child: Text(
        evaluated ? 'Evaluated' : 'Pending Evaluation',
        style: TextStyle(color: fg, fontWeight: FontWeight.w800, fontSize: 11),
      ),
    );
  }

  (String, String, String?) _overviewCard(String title, EvaluationComponentResult? component) {
    if (component == null || component.status != 'evaluated') {
      return (title, '—', component?.reason ?? 'Not scored in this run');
    }
    return (
      title,
      formatAccuracyPercent(component.metric('accuracy')),
      'F1 ${formatMetricScore(component.metric('macro_f1'))}  ·  ${component.caseCount} cases',
    );
  }

  Widget _censusChip(String label, String value) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          value,
          style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16, color: DesignTokens.ink),
        ),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(color: DesignTokens.muted, fontSize: 12)),
      ],
    );
  }
}

class _OverviewCardGrid extends StatelessWidget {
  const _OverviewCardGrid({required this.columns, required this.cards});

  final int columns;
  final List<(String, String, String?)> cards;

  @override
  Widget build(BuildContext context) {
    const gap = 12.0;
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final cardWidth = columns == 1 ? width : (width - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            for (final card in cards)
              SizedBox(
                width: cardWidth,
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: DesignTokens.bgGrey,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: const Color(0xFFE2E8F0)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        card.$1,
                        style: const TextStyle(
                          color: DesignTokens.muted,
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        card.$2,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: DesignTokens.ink,
                          fontSize: 28,
                          fontWeight: FontWeight.w900,
                          height: 1.1,
                        ),
                      ),
                      if (card.$3 != null) ...[
                        const SizedBox(height: 6),
                        Text(card.$3!, style: const TextStyle(color: DesignTokens.muted, fontSize: 11)),
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

class ClassificationClassifierSections extends StatelessWidget {
  const ClassificationClassifierSections({
    super.key,
    required this.components,
    required this.matrices,
  });

  final List<EvaluationComponentResult> components;
  final Map<String, EvaluationConfusionMatrix> matrices;

  @override
  Widget build(BuildContext context) {
    final specs = [
      (
        'Question Classifier',
        'classify_question',
        'Rules + taxonomy similarity only — never an LLM.',
      ),
      (
        'Chunk Classifier — LLM Enabled',
        'classify_chunk(allow_llm=True)',
        'Rules + similarity, then optional LLM fallback when confidence is low.',
      ),
      (
        'Chunk Classifier — LLM Disabled',
        'classify_chunk(allow_llm=False)',
        'Rules + similarity only for this run.',
      ),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Classifier results',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: DesignTokens.ink),
        ),
        const SizedBox(height: 12),
        for (final spec in specs) ...[
          _ClassifierResultSection(
            title: spec.$1,
            componentName: spec.$2,
            subtitle: spec.$3,
            component: classificationByName(components, spec.$2),
            matrix: matrices[spec.$2],
          ),
          const SizedBox(height: 16),
        ],
      ],
    );
  }
}

class _ClassifierResultSection extends StatelessWidget {
  const _ClassifierResultSection({
    required this.title,
    required this.componentName,
    required this.subtitle,
    required this.component,
    required this.matrix,
  });

  final String title;
  final String componentName;
  final String subtitle;
  final EvaluationComponentResult? component;
  final EvaluationConfusionMatrix? matrix;

  @override
  Widget build(BuildContext context) {
    final c = component;
    return Container(
      key: Key('eval-classifier-section-$componentName'),
      width: double.infinity,
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
          Text(title, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16, color: DesignTokens.ink)),
          const SizedBox(height: 2),
          Text('$componentName · $subtitle', style: const TextStyle(color: DesignTokens.muted, fontSize: 12)),
          const SizedBox(height: 12),
          if (c == null || c.status != 'evaluated')
            Text(
              c == null
                  ? 'Not available: this component is not in the selected run.'
                  : 'Not available (${c.status}${c.reason != null ? ": ${c.reason}" : ""}).',
              style: const TextStyle(color: DesignTokens.muted, fontSize: 12, fontStyle: FontStyle.italic),
            )
          else ...[
            Wrap(
              spacing: 16,
              runSpacing: 8,
              children: [
                _metricChip('Accuracy', formatAccuracyPercent(c.metric('accuracy'))),
                _metricChip('Macro Precision', formatMetricScore(c.metric('macro_precision'))),
                _metricChip('Macro Recall', formatMetricScore(c.metric('macro_recall'))),
                _metricChip('Macro F1', formatMetricScore(c.metric('macro_f1'))),
                _metricChip('Cases', '${c.caseCount}'),
              ],
            ),
            const SizedBox(height: 16),
            if (matrix != null)
              ConfusionMatrixGrid(matrix: matrix!)
            else
              const Text(
                'No confusion matrix was returned for this component.',
                style: TextStyle(color: DesignTokens.muted, fontSize: 12),
              ),
            const SizedBox(height: 16),
            PerClassPerformanceTable(rows: c.perClassBreakdown()),
          ],
        ],
      ),
    );
  }

  Widget _metricChip(String name, String value) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: DesignTokens.bgGrey,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(name, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: DesignTokens.muted)),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w900, color: DesignTokens.ink)),
        ],
      ),
    );
  }
}

class PerClassPerformanceTable extends StatelessWidget {
  const PerClassPerformanceTable({super.key, required this.rows});

  final List<ClassificationClassBreakdown> rows;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Per-subcategory performance',
          style: TextStyle(fontWeight: FontWeight.w800, fontSize: 14, color: DesignTokens.ink),
        ),
        const SizedBox(height: 8),
        if (rows.isEmpty)
          const Text(
            'No per-class breakdown was persisted for this component.',
            style: TextStyle(color: DesignTokens.muted, fontSize: 12, fontStyle: FontStyle.italic),
          )
        else
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              headingRowColor: WidgetStateProperty.all(DesignTokens.bgGrey),
              columns: const [
                DataColumn(label: Text('Subcategory')),
                DataColumn(label: Text('Precision'), numeric: true),
                DataColumn(label: Text('Recall'), numeric: true),
                DataColumn(label: Text('F1-score'), numeric: true),
                DataColumn(label: Text('Support'), numeric: true),
              ],
              rows: [
                for (final row in rows)
                  DataRow(
                    cells: [
                      DataCell(
                        SizedBox(
                          width: 220,
                          child: Text(row.label, maxLines: 2, overflow: TextOverflow.ellipsis),
                        ),
                      ),
                      DataCell(Text(row.precision == null ? '—' : formatMetricScore(row.precision))),
                      DataCell(Text(row.recall == null ? '—' : formatMetricScore(row.recall))),
                      DataCell(Text(row.f1 == null ? '—' : formatMetricScore(row.f1))),
                      DataCell(Text(row.support == null ? '—' : '${row.support}')),
                    ],
                  ),
              ],
            ),
          ),
      ],
    );
  }
}
