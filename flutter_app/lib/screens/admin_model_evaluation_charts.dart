/// fl_chart widgets for the Model Evaluation dashboard: model-comparison
/// bar charts, performance (latency/token) bar charts, and the confusion
/// matrix grid (never an fl_chart widget -- fl_chart has no heatmap/matrix
/// type, so a styled table is the faithful choice, not forced into a bar
/// or line chart it doesn't fit).
///
/// Every chart here is purely presentational: it takes already-fetched
/// [EvaluationComponentResult]/[EvaluationConfusionMatrix] data and never
/// calls the API itself, so these widgets are trivially unit-testable with
/// hand-built data.
library;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../models/evaluation_models.dart';

/// One labeled bar. [value] is null when the metric was never computed --
/// such a bar is never drawn (never silently rendered as a zero-height
/// bar indistinguishable from a real 0.0); its label is instead listed in
/// the "not available" caption below the chart.
class EvalBarEntry {
  const EvalBarEntry({required this.label, required this.value, required this.color});

  final String label;
  final double? value;
  final Color color;
}

class EvalBarChartCard extends StatelessWidget {
  const EvalBarChartCard({
    super.key,
    required this.title,
    required this.subtitle,
    required this.bars,
    this.maxY,
  });

  final String title;
  final String subtitle;
  final List<EvalBarEntry> bars;
  final double? maxY;

  @override
  Widget build(BuildContext context) {
    final available = <EvalBarEntry>[];
    final unavailable = <String>[];
    for (final bar in bars) {
      if (bar.value == null) {
        unavailable.add(bar.label);
      } else {
        available.add(bar);
      }
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15, color: DesignTokens.ink),
          ),
          const SizedBox(height: 2),
          Text(subtitle, style: const TextStyle(color: DesignTokens.muted, fontSize: 12)),
          const SizedBox(height: 14),
          if (available.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 24),
              child: Text(
                'No data available for this chart yet.',
                style: TextStyle(color: DesignTokens.muted, fontWeight: FontWeight.w600),
              ),
            )
          else
            SizedBox(
              height: 220,
              child: BarChart(
                BarChartData(
                  maxY: maxY ?? _autoMaxY(available),
                  minY: 0,
                  alignment: BarChartAlignment.spaceAround,
                  gridData: const FlGridData(show: true, drawVerticalLine: false),
                  borderData: FlBorderData(show: false),
                  barTouchData: BarTouchData(
                    touchTooltipData: BarTouchTooltipData(
                      getTooltipItem: (group, groupIndex, rod, rodIndex) {
                        final entry = available[group.x.toInt()];
                        return BarTooltipItem(
                          '${entry.label}\n${rod.toY.toStringAsFixed(3)}',
                          const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                        );
                      },
                    ),
                  ),
                  titlesData: FlTitlesData(
                    topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(showTitles: true, reservedSize: 36),
                    ),
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 42,
                        getTitlesWidget: (value, meta) {
                          final index = value.toInt();
                          if (index < 0 || index >= available.length) return const SizedBox.shrink();
                          return Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(
                              available[index].label,
                              textAlign: TextAlign.center,
                              style: const TextStyle(fontSize: 10, color: DesignTokens.muted, fontWeight: FontWeight.w700),
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                  barGroups: [
                    for (var i = 0; i < available.length; i++)
                      BarChartGroupData(
                        x: i,
                        barRods: [
                          BarChartRodData(
                            toY: available[i].value!,
                            color: available[i].color,
                            width: 22,
                            borderRadius: BorderRadius.circular(4),
                          ),
                        ],
                      ),
                  ],
                ),
              ),
            ),
          if (unavailable.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              'Not available: ${unavailable.join(', ')}',
              key: const Key('eval-chart-unavailable-caption'),
              style: const TextStyle(color: DesignTokens.muted, fontSize: 11, fontStyle: FontStyle.italic),
            ),
          ],
        ],
      ),
    );
  }

  double _autoMaxY(List<EvalBarEntry> available) {
    final maxValue = available.map((b) => b.value!).fold<double>(0, (a, b) => a > b ? a : b);
    if (maxValue <= 1.0) return 1.0;
    return (maxValue * 1.2).ceilToDouble();
  }
}

/// Styled grid for one confusion matrix -- deliberately not an fl_chart
/// widget (no heatmap/matrix chart type exists there). Shown only for
/// classification components, per the "confusion matrices only for
/// classification" requirement; callers decide which components to pass.
class ConfusionMatrixGrid extends StatelessWidget {
  const ConfusionMatrixGrid({super.key, required this.matrix});

  final EvaluationConfusionMatrix matrix;

  @override
  Widget build(BuildContext context) {
    final labels = matrix.labels;
    var maxCell = 1;
    for (final row in matrix.matrix) {
      for (final cell in row) {
        if (cell > maxCell) maxCell = cell;
      }
    }
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            matrix.component,
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14, color: DesignTokens.ink),
          ),
          const SizedBox(height: 2),
          Text(
            '${matrix.caseCount} case${matrix.caseCount == 1 ? '' : 's'} · rows = true label, columns = predicted label',
            style: const TextStyle(color: DesignTokens.muted, fontSize: 11),
          ),
          const SizedBox(height: 8),
          const Text(
            'Rows = actual subcategory, columns = predicted. Darker cells have higher counts. Bold diagonal cells are correct classifications.',
            style: TextStyle(color: DesignTokens.muted, fontSize: 11),
          ),
          const SizedBox(height: 12),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Table(
              defaultColumnWidth: const FixedColumnWidth(72),
              border: TableBorder.all(color: DesignTokens.border),
              children: [
                TableRow(
                  decoration: const BoxDecoration(color: DesignTokens.bgGrey),
                  children: [
                    const _MatrixCell(text: '', header: true),
                    for (final label in labels) _MatrixCell(text: label, header: true),
                  ],
                ),
                for (var row = 0; row < matrix.matrix.length; row++)
                  TableRow(
                    children: [
                      _MatrixCell(text: row < labels.length ? labels[row] : '?', header: true),
                      for (var col = 0; col < matrix.matrix[row].length; col++)
                        _MatrixCell(
                          text: '${matrix.matrix[row][col]}',
                          intensity: _heatmapIntensity(matrix.matrix[row][col], maxCell),
                          diagonal: row == col,
                        ),
                    ],
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

double _heatmapIntensity(int value, int maxCell) {
  if (maxCell <= 0 || value <= 0) return 0;
  return (value / maxCell).clamp(0.0, 1.0);
}

class _MatrixCell extends StatelessWidget {
  const _MatrixCell({
    required this.text,
    this.header = false,
    this.intensity = 0,
    this.diagonal = false,
  });

  final String text;
  final bool header;
  final double intensity;
  final bool diagonal;

  @override
  Widget build(BuildContext context) {
    final fill = header
        ? DesignTokens.bgGrey
        : Color.lerp(Colors.white, const Color(0xFF5C0A0F), 0.12 + intensity * 0.72)!;
    final fg = header || intensity < 0.45 ? DesignTokens.ink : Colors.white;
    return ColoredBox(
      color: fill,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
        child: Text(
          text,
          textAlign: TextAlign.center,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 12,
            fontWeight: header || diagonal ? FontWeight.w800 : FontWeight.w600,
            color: fg,
          ),
        ),
      ),
    );
  }
}

class EvalComparatorTable extends StatelessWidget {
  const EvalComparatorTable({
    super.key,
    required this.title,
    required this.subtitle,
    required this.rows,
  });

  final String title;
  final String subtitle;
  final List<EvalComparatorRow> rows;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15, color: DesignTokens.ink)),
          const SizedBox(height: 2),
          Text(subtitle, style: const TextStyle(color: DesignTokens.muted, fontSize: 12)),
          const SizedBox(height: 14),
          for (final row in rows) ...[
            Text(row.label, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13, color: DesignTokens.ink)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 18,
              runSpacing: 10,
              children: [
                for (final metric in row.metrics) _ComparatorMetric(metric: metric),
              ],
            ),
            const SizedBox(height: 16),
          ],
        ],
      ),
    );
  }
}

class EvalComparatorRow {
  const EvalComparatorRow({required this.label, required this.metrics});

  final String label;
  final List<EvalComparatorMetric> metrics;
}

class EvalComparatorMetric {
  const EvalComparatorMetric({required this.name, required this.value});

  final String name;
  final double? value;
}

class _ComparatorMetric extends StatelessWidget {
  const _ComparatorMetric({required this.metric});

  final EvalComparatorMetric metric;

  @override
  Widget build(BuildContext context) {
    final value = metric.value;
    final display = value == null ? 'N/A' : value.toStringAsFixed(4);
    return SizedBox(
      width: 150,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(metric.name, style: const TextStyle(fontSize: 11, color: DesignTokens.muted, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(
            display,
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              fontStyle: value == null ? FontStyle.italic : FontStyle.normal,
              color: value == null ? DesignTokens.muted : DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: value == null ? 0 : value.clamp(0.0, 1.0),
              minHeight: 8,
              backgroundColor: DesignTokens.bgGrey,
              color: value == null ? DesignTokens.border : DesignTokens.maroon,
            ),
          ),
        ],
      ),
    );
  }
}
